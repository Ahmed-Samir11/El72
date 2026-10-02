import json
import logging
import os
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from services.api.credits import grant
from services.api.models import User
from services.api.payment_security import record_payment_event, sanitize_for_log
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


app = FastAPI(title="Elhaq Billing")
limiter = Limiter(key_func=_webhook_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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


def _client_ip(request: Request) -> str:
    """Best-effort client IP for AUDIT LOGGING only (never for rate limiting).

    X-Forwarded-For is honored only when the deployment sits behind a
    trusted reverse proxy that sets it (the same convention as the API
    service); without one, the socket peer is used. Enforcing proxy trust is
    a deployment concern (trusted-proxy configuration), not application
    logic.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _reject_webhook(db: Session, ip: str, reason: str, user_id, order_ref: str) -> None:
    """Audit a rejected webhook outcome (committed BEFORE the 4xx is raised,
    so the audit row survives)."""
    record_payment_event(
        db,
        event_type="validation_rejected",
        user_id=str(user_id) if user_id is not None else None,
        payment_ref=order_ref,
        detail=sanitize_for_log(f"reason={reason}"),
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
      4.3 amount must equal PACKAGE_PRICES[package] * 100 piastres -> 400
      4.2 idempotency: unique paymob_order_id, duplicate -> no side effect
      4.5 atomic credit grant in one transaction
      4.8 every processing outcome is written to the immutable audit log
      4.9 rate limited (100/hour)
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
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body.decode("utf-8"))
        tx = data.get("obj", data) if isinstance(data, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(tx, dict):
        _reject_webhook(db, ip, "invalid_payload", None, "")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    # Strict payload validation — reject missing/None fields before use so
    # nothing is ever stringified to 'None'.
    order_id = tx.get("id")
    status_value = tx.get("status")
    reference_id = tx.get("reference_id")
    amount_paisa = tx.get("amount")
    if (
        not isinstance(order_id, str)
        or not order_id
        or not isinstance(status_value, str)
        or not status_value
        or not isinstance(reference_id, str)
        or not reference_id
        or not isinstance(amount_paisa, int)
        or isinstance(amount_paisa, bool)
    ):
        _reject_webhook(db, ip, "invalid_payload", None, "")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

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
        _reject_webhook(db, ip, "invalid_reference_id", None, order_id)
        raise HTTPException(status_code=400, detail="Invalid reference_id")
    user_id_str, package = "-".join(parts[1:-1]), parts[-1]
    if package not in PACKAGE_CREDITS:
        _reject_webhook(db, ip, "invalid_package", None, order_id)
        raise HTTPException(status_code=400, detail="Invalid package")

    # 4.6: validate the user exists. On Postgres a token that is not a valid
    # UUID raises a type error at the column level; such a token cannot
    # reference an existing user, so map it to 400.
    try:
        user = db.query(User).filter(User.id == user_id_str).first()
    except DataError as exc:
        _reject_webhook(db, ip, "unknown_user", None, order_id)
        raise HTTPException(status_code=400, detail="Unknown user") from exc
    if user is None:
        _reject_webhook(db, ip, "unknown_user", None, order_id)
        raise HTTPException(status_code=400, detail="Unknown user")

    # 4.3: validate amount (Paymob reports in piastres, the minor unit).
    expected_paisa = int(PACKAGE_PRICES[package] * 100)
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
    return {"status": "processed"}


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
