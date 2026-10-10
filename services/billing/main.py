import json
import logging
import os
from decimal import Decimal
import time
from prometheus_client import Counter, Histogram, make_asgi_app

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from services.api.credits import grant
from services.api.models import User
from services.api.payment_security import (
    record_payment_event,
    sanitize_for_log,
    security_monitor,
)
from services.billing.models import PaymentLog
from services.common.paymob import verify_paymob_hmac

logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./billing.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PAYMOB_HMAC_SECRET = os.getenv("PAYMOB_HMAC_SECRET", "")
PAYMOB_SIGNATURE_HEADER = os.getenv("PAYMOB_SIGNATURE_HEADER", "X-Paymob-Signature")
PAYMOB_CHECKOUT_URL = os.getenv("PAYMOB_CHECKOUT_URL", "")

PACKAGE_CREDITS = {"standard": 10, "premium": 30}
PACKAGE_PRICES = {"standard": 30.0, "premium": 90.0}
# Exact piastre (minor-unit) values — the validation path uses integers,
# never float multiplication.
PACKAGE_PRICES_PAISA = {"standard": 3000, "premium": 9000}
WEBHOOK_STATUSES = {"succeeded", "failed", "canceled"}

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _webhook_rate_limit_key(request) -> str:
    """Rate-limit webhooks by SOCKET PEER IP, not X-Forwarded-For.

    The caller is Paymob's egress infrastructure, not an end user behind a
    proxy, so the transport peer is the correct identity. A spoofed
    X-Forwarded-For header from an untrusted source must not be able to
    shard (or exhaust) the quota.

    Note: behind a reverse proxy the socket peer is the proxy itself, so
    the limit acts as a GLOBAL flood guard for the endpoint — which is
    exactly the plan's intent (4.9: "webhook endpoint is rate-limited
    (100/hour); if exceeded → 429").
    """
    return request.client.host if request.client else "unknown"

HTTP_REQUESTS = Counter(
    "el72_billing_http_requests_total",
    "HTTP requests handled by the billing service",
    ["method", "route", "status_code"],
)

HTTP_REQUEST_DURATION = Histogram(
    "el72_billing_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
)

app = FastAPI(title="Elhaq Billing")

# Multi-instance deployments should set PAYMOB_RATE_LIMIT_REDIS so the
# rate-limit state is shared across workers/processes (slowapi in-memory
# state is process-local by default).
RATE_LIMIT_STORAGE_URI = os.getenv("PAYMOB_RATE_LIMIT_REDIS", "")
limiter_kwargs: dict = {"key_func": _webhook_rate_limit_key}
if RATE_LIMIT_STORAGE_URI:
    limiter_kwargs["storage_uri"] = RATE_LIMIT_STORAGE_URI
limiter = Limiter(**limiter_kwargs)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.middleware("http")
async def observe_http_requests(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")

        HTTP_REQUESTS.labels(
            request.method, route_path, str(status_code)
        ).inc()

        HTTP_REQUEST_DURATION.labels(
            request.method, route_path
        ).observe(time.perf_counter() - start)


app.mount("/metrics", make_asgi_app())

# Pydantic models
class PurchaseRequest(BaseModel):
    """Requested credit package for a Paymob checkout."""

    user_id: str
    tier: str


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_paymob_webhook(request: Request, body: bytes) -> bool:
    """Validate a Paymob webhook against the raw request body."""
    signature = request.headers.get(PAYMOB_SIGNATURE_HEADER, "")
    if not PAYMOB_HMAC_SECRET or not signature:
        return False
    return verify_paymob_hmac(PAYMOB_HMAC_SECRET, body, signature)


# X-Forwarded-For is honored ONLY when the deployment explicitly declares a
# trusted reverse proxy (TRUST_PROXY=1); otherwise an untrusted client could
# forge the audit IP.
TRUST_PROXY = os.getenv("TRUST_PROXY", "") == "1"


def _client_ip(request: Request) -> str:
    """Best-effort client IP for AUDIT LOGGING only (never for rate limiting).

    X-Forwarded-For is honored only when TRUST_PROXY=1 (deployment behind a
    trusted reverse proxy); otherwise the socket peer is used so an untrusted
    client cannot forge the recorded IP.
    """
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _reject_webhook(db: Session, ip: str, detail: str, user_id, order_ref: str) -> None:
    """Audit a rejected webhook outcome (committed BEFORE the 4xx is raised,
    so the audit row survives). ``detail`` carries forensic context (reason +
    the offending token/package); it is sanitized before storage."""
    record_payment_event(
        db,
        event_type="validation_rejected",
        user_id=str(user_id) if user_id is not None else None,
        payment_ref=order_ref,
        detail=sanitize_for_log(detail),
        ip_address=ip,
    )
    db.commit()


def _is_duplicate_order_error(exc: IntegrityError) -> bool:
    """True ONLY for a unique violation on payment_logs.paymob_order_id.

    Other integrity failures (foreign keys, NOT NULL, ...) must propagate —
    they are bugs or attacks, not duplicate deliveries.
    """
    orig = str(exc.orig) if exc.orig else ""
    return "paymob_order_id" in orig and (
        "unique" in orig.lower() or "duplicate" in orig.lower()
    )


@app.post("/purchase")
def create_purchase(request: PurchaseRequest) -> dict:
    """Create a purchase intent for a configured Paymob checkout flow."""
    if request.tier not in PACKAGE_CREDITS:
        raise HTTPException(status_code=400, detail="Invalid package")
    if not PAYMOB_CHECKOUT_URL:
        raise HTTPException(
            status_code=503, detail="Payment provider is not configured"
        )
    return {
        "tier": request.tier,
        "credits": PACKAGE_CREDITS[request.tier],
        "amount_egp": PACKAGE_PRICES[request.tier],
        "checkout_url": PAYMOB_CHECKOUT_URL,
    }


@app.post("/webhook/paymob")
@limiter.limit("100/hour")
async def paymob_webhook(request: Request, db: Session = Depends(get_db)):
    """Paymob webhook handler — the single source of truth for
    "payment succeeded".

    Security gates (plan Feature 4):
      4.1 HMAC-SHA512 signature on the raw body -> 401
      4.4 reference_id must match elhaq-{user_uuid}-{package} -> 400
      4.6 user must exist -> 400
      4.3 amount must equal the package's exact piastre value -> 400
      4.2 idempotency: unique paymob_order_id, duplicate -> no side effect
      4.5 atomic credit grant in one transaction
      4.8 every processing outcome is written to the immutable audit log
      4.9 rate limited (100/hour)

    The endpoint is async (the raw body requires ``await``) and performs
    short-lived synchronous database calls; webhook traffic is low-volume
    and each transaction is millisecond-scale, so event-loop blocking is
    acceptable for this endpoint.
    """
    body = await request.body()
    ip = _client_ip(request)

    # 4.1: signature verification is the primary security gate.
    if not verify_paymob_webhook(request, body):
        record_payment_event(
            db,
            event_type="webhook_signature_failed",
            payment_ref="",
            detail=sanitize_for_log("signature verification failed"),
            ip_address=ip,
        )
        db.commit()
        # Feature 5 wiring (deferred to Feature 2): alert on 5+ failed
        # signatures within 1 minute (possible webhook forgery attempt).
        if security_monitor.record_failure("webhook_signature_failed"):
            logger.warning(
                "Security alert: 5+ failed webhook signatures within 1 minute"
            )
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body.decode("utf-8"))
        tx = data.get("obj", data) if isinstance(data, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Malformed bodies are rejected AND audited (immutable trail).
        _reject_webhook(db, ip, "invalid_payload: unparseable body", None, "")
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(tx, dict):
        _reject_webhook(db, ip, "invalid_payload: not an object", None, "")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    # Strict payload validation — reject missing/None fields before use so
    # nothing is ever stringified to 'None'.
    order_id = tx.get("id")
    status_value = tx.get("status")
    reference_id = tx.get("reference_id")
    amount_paisa = tx.get("amount")
    currency = tx.get("currency")
    if (
        not isinstance(order_id, str)
        or not order_id
        or not isinstance(status_value, str)
        or not status_value
        or not isinstance(reference_id, str)
        or not reference_id
        or not isinstance(amount_paisa, int)
        or isinstance(amount_paisa, bool)
        or not isinstance(currency, str)
        or not currency
    ):
        _reject_webhook(db, ip, "invalid_payload: missing/typed fields", None, "")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    # Status whitelist: only the Paymob terminal statuses we understand are
    # accepted; anything else is a rejected (and audited) payload.
    if status_value not in WEBHOOK_STATUSES:
        _reject_webhook(db, ip, f"unknown_status: {status_value}", None, order_id)
        raise HTTPException(status_code=400, detail="Invalid status")

    # 4.2: idempotency FIRST — a duplicate delivery short-circuits before any
    # other validation (no user lookup, no side effects) and is audited.
    existing = db.execute(
        text("SELECT 1 FROM payment_logs WHERE paymob_order_id = :order_id"),
        {"order_id": order_id},
    ).first()
    if existing is not None:
        record_payment_event(
            db,
            event_type="webhook_duplicate",
            payment_ref=order_id,
            detail=sanitize_for_log("duplicate delivery"),
            ip_address=ip,
        )
        db.commit()
        return {"status": "duplicate"}

    # 4.4: validate reference_id format: elhaq-{user_id}-{package}. User ids
    # may contain dashes (UUIDs), so the package is the LAST segment and the
    # user token is everything in between. The token must also resolve to a
    # real user (checked below); in production (Postgres) every existing
    # user id is a UUID, so a tampered token is rejected by the existence
    # check.
    parts = reference_id.split("-")
    if len(parts) < 3 or parts[0] != "elhaq" or not parts[1]:
        _reject_webhook(
            db,
            ip,
            f"invalid_reference_id: {reference_id}",
            None,
            order_id,
        )
        raise HTTPException(status_code=400, detail="Invalid reference_id")
    user_id_str, package = "-".join(parts[1:-1]), parts[-1]
    if package not in PACKAGE_CREDITS:
        _reject_webhook(db, ip, f"invalid_package: {package}", None, order_id)
        raise HTTPException(status_code=400, detail="Invalid package")

    # 4.6: validate the user exists. On Postgres a token that is not a valid
    # UUID raises a type error at the column level; such a token cannot
    # reference an existing user, so map it to 400.
    try:
        user = db.query(User).filter(User.id == user_id_str).first()
    except DataError as exc:
        _reject_webhook(db, ip, f"unknown_user: token={user_id_str}", None, order_id)
        raise HTTPException(status_code=400, detail="Unknown user") from exc
    if user is None:
        _reject_webhook(db, ip, f"unknown_user: token={user_id_str}", None, order_id)
        raise HTTPException(status_code=400, detail="Unknown user")

    # Currency must be EGP (the only currency this deployment sells in).
    if currency != "EGP":
        _reject_webhook(db, ip, f"invalid_currency: {currency}", None, order_id)
        raise HTTPException(status_code=400, detail="Invalid currency")

    # 4.3: validate amount (Paymob reports in piastres, the minor unit) —
    # integer comparison against the exact package price.
    expected_paisa = PACKAGE_PRICES_PAISA[package]
    if amount_paisa != expected_paisa:
        record_payment_event(
            db,
            event_type="amount_mismatch",
            user_id=str(user.id),
            payment_ref=order_id,
            detail=sanitize_for_log(f"expected {expected_paisa} piastres"),
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Amount mismatch")

    if status_value != "succeeded":
        # failed/canceled: audit the outcome and grant nothing. Deliberately
        # NO PaymentLog row — a terminal-failure record must not occupy the
        # unique paymob_order_id, so a later succeeded delivery of the same
        # order remains processable.
        record_payment_event(
            db,
            event_type="webhook_received",
            user_id=str(user.id),
            payment_ref=order_id,
            detail=sanitize_for_log(f"status={status_value}"),
            ip_address=ip,
        )
        db.commit()
        logger.info(
            "Webhook ignored for %s (status=%s)",
            order_id,
            status_value,
            extra={"order_id": order_id},
        )
        # Reflect the terminal state on the payment rows so /payment/status
        # reports the failure to the user (plan Feature 1: "Failed payment
        # -> user sees error, no credits granted").
        _update_card_payment_status(db, order_id, status_value)
        _update_wallet_payment_status(db, order_id, status_value)
        return {"status": "ignored"}

    # 4.5: atomic credit grant — payment log + credits + audit in ONE
    # transaction; any failure rolls everything back.
    try:
        db.add(
            PaymentLog(
                user_id=user.id,
                paymob_order_id=order_id,
                amount=Decimal(amount_paisa) / 100,
                currency="EGP",
                status=status_value,
                tier=package,
            )
        )
        grant(db, user, PACKAGE_CREDITS[package], reason=f"paymob_{package}")
        record_payment_event(
            db,
            event_type="webhook_received",
            user_id=str(user.id),
            payment_ref=order_id,
            detail=sanitize_for_log(f"status={status_value}"),
            ip_address=ip,
        )
        db.commit()
    except IntegrityError as exc:
        # Only a unique violation on paymob_order_id means we lost a race to
        # a duplicate delivery; any other integrity failure propagates.
        db.rollback()
        if not _is_duplicate_order_error(exc):
            raise
        record_payment_event(
            db,
            event_type="webhook_duplicate",
            payment_ref=order_id,
            detail=sanitize_for_log("duplicate delivery (race)"),
            ip_address=ip,
        )
        db.commit()
        return {"status": "duplicate"}

    logger.info(
        "Payment processed",
        extra={
            "order_id": order_id,
            "amount": str(Decimal(amount_paisa) / 100),
            "tier": package,
        },
    )

    # Finding #3: transition the CardPayment status to the
    # webhook-confirmed terminal state so /payment/status reflects reality.
    _update_card_payment_status(db, order_id, status_value)
    # Same for wallet payments (Feature 2): the webhook is the source of
    # truth for the payment's fate.
    _update_wallet_payment_status(db, order_id, status_value)

    return {"status": "processed"}


def _update_card_payment_status(db: Session, order_id: str, status_value: str) -> None:
    """Transition the CardPayment row to the webhook-confirmed terminal state.

    The CardPayment table lives in the API schema; the billing service
    shares the same DATABASE_URL in production. We use a raw UPDATE so we
    do not need to import the ORM model across services.

    Prior terminal states (``failed``/``canceled``) are transitioned too:
    the webhook is the source of truth for the payment's fate, so a later
    ``succeeded`` delivery of the same order must be visible on the row (and
    on /payment/status), not shadowed by an earlier failure.

    The UPDATE is committed explicitly: the session is closed (not
    committed) by the get_db teardown, so without this the transition
    would be silently rolled back.
    """
    from sqlalchemy import text as _text

    try:
        db.execute(
            _text(
                "UPDATE card_payments SET status = :status "
                "WHERE paymob_payment_id = :order_id "
                "AND status IN ('pending', 'failed', 'canceled')"
            ),
            {"status": status_value, "order_id": order_id},
        )
        db.commit()
    except Exception:
        # Non-fatal: the CardPayment row may not exist (e.g. manual payment
        # flow) or the table may be absent in a billing-only deployment.
        db.rollback()
        logger.warning("Could not update card_payments status for %s", order_id)


def _update_wallet_payment_status(
    db: Session, order_id: str, status_value: str
) -> None:
    """Transition the WalletPayment row to the webhook-confirmed terminal
    state (Feature 2).

    Same semantics as :func:`_update_card_payment_status`: the webhook is
    the source of truth, prior terminal states are transitioned, and the
    UPDATE is committed explicitly (the get_db teardown closes without
    committing, so an uncommitted transition would roll back).
    """
    from sqlalchemy import text as _text

    try:
        db.execute(
            _text(
                "UPDATE wallet_payments SET status = :status "
                "WHERE paymob_payment_id = :order_id "
                "AND status IN ('pending_otp', 'processing', 'failed', 'canceled')"
            ),
            {"status": status_value, "order_id": order_id},
        )
        db.commit()
    except Exception:
        # Non-fatal: the WalletPayment row may not exist (card or manual
        # payment) or the table may be absent in a billing-only deployment.
        db.rollback()
        logger.warning("Could not update wallet_payments status for %s", order_id)


@app.get("/pricing")
def get_dynamic_pricing():
    return {
        "currency": "EGP",
        "packages": {
            "free": {"credits": 3, "price_egp": 0},
            "standard": {"credits": 10, "price_egp": 30},
            "premium": {"credits": 30, "price_egp": 90},
        },
    }
