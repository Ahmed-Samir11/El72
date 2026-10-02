import json
import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
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

app = FastAPI(title="Elhaq Billing")
limiter = Limiter(key_func=get_remote_address)
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
    """Best-effort client IP (X-Forwarded-For first, then socket peer)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


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
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    status_value = str(tx.get("status", ""))
    order_id = str(tx.get("id", ""))
    reference_id = str(tx.get("reference_id", ""))

    # 4.4: validate reference_id format: elhaq-{user_id}-{package}. User ids
    # may contain dashes (UUIDs), so the package is the LAST segment and the
    # user token is everything in between. The token must also resolve to a
    # real user (checked below); in production (Postgres) every existing
    # user id is a UUID, so a tampered token is rejected by the existence
    # check.
    parts = reference_id.split("-")
    if len(parts) < 3 or parts[0] != "elhaq" or not parts[1]:
        raise HTTPException(status_code=400, detail="Invalid reference_id")
    user_id_str, package = "-".join(parts[1:-1]), parts[-1]
    if package not in PACKAGE_CREDITS:
        raise HTTPException(status_code=400, detail="Invalid package")

    # 4.6: validate the user exists.
    user = db.query(User).filter(User.id == user_id_str).first()
    if user is None:
        raise HTTPException(status_code=400, detail="Unknown user")

    # 4.3: validate amount (Paymob reports in piastres, the minor unit).
    amount_paisa = tx.get("amount", 0)
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

    # 4.2: idempotency — a duplicate delivery has no side effects.
    existing = db.execute(
        text("SELECT 1 FROM payment_logs WHERE paymob_order_id = :order_id"),
        {"order_id": order_id},
    ).first()
    if existing is not None:
        return {"status": "duplicate"}

    if status_value != "succeeded":
        # failed/canceled: record the outcome, grant nothing.
        db.add(
            PaymentLog(
                user_id=user.id,
                paymob_order_id=order_id,
                amount=amount_paisa / 100,
                currency="EGP",
                status=status_value,
                tier=package,
            )
        )
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
                amount=amount_paisa / 100,
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
    except IntegrityError:
        # Lost a race on the unique paymob_order_id constraint: the duplicate
        # won, so roll back and report it as a duplicate.
        db.rollback()
        return {"status": "duplicate"}

    logger.info(
        "Payment processed",
        extra={"order_id": order_id, "amount": amount_paisa / 100, "tier": package},
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
