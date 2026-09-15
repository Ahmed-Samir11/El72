import os
import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from services.billing.models import Base, PaymentLog
from services.common.paymob import verify_paymob_hmac

logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./billing.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PAYMOB_HMAC_SECRET = os.getenv("PAYMOB_HMAC_SECRET", "")
PAYMOB_SIGNATURE_HEADER = os.getenv(
    "PAYMOB_SIGNATURE_HEADER", "X-Paymob-Signature"
)
PAYMOB_CHECKOUT_URL = os.getenv("PAYMOB_CHECKOUT_URL", "")

PACKAGE_CREDITS = {"standard": 10, "premium": 30}
PACKAGE_PRICES = {"standard": 30.0, "premium": 90.0}

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app = FastAPI(title="Elhaq Billing")

# Pydantic models
class PaymentWebhook(BaseModel):
    order_id: str
    amount: float
    currency: str
    status: str
    user_id: UUID
    tier: str


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


@app.post("/purchase")
def create_purchase(request: PurchaseRequest) -> dict:
    """Create a purchase intent for a configured Paymob checkout flow."""
    if request.tier not in PACKAGE_CREDITS:
        raise HTTPException(status_code=400, detail="Invalid package")
    if not PAYMOB_CHECKOUT_URL:
        raise HTTPException(status_code=503, detail="Payment provider is not configured")
    return {
        "tier": request.tier,
        "credits": PACKAGE_CREDITS[request.tier],
        "amount_egp": PACKAGE_PRICES[request.tier],
        "checkout_url": PAYMOB_CHECKOUT_URL,
    }

@app.post("/webhook/paymob")
async def paymob_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if not verify_paymob_webhook(request, body):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data_dict = json.loads(body.decode("utf-8"))
        if isinstance(data_dict.get("obj"), dict):
            data_dict = data_dict["obj"]
        data = PaymentWebhook(**data_dict)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    if data.currency != "EGP" or data.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payment details")

    if data.status == "success":
        if data.tier not in PACKAGE_CREDITS:
            raise HTTPException(status_code=400, detail="Invalid package")
        if data.amount != PACKAGE_PRICES[data.tier]:
            raise HTTPException(status_code=400, detail="Payment amount does not match package")
        existing = db.execute(
            text("SELECT 1 FROM payment_logs WHERE paymob_order_id = :order_id"),
            {"order_id": data.order_id},
        ).first()
        if existing:
            return {"status": "processed", "duplicate": True}

        # Log payment
        payment_log = PaymentLog(
            user_id=data.user_id,
            paymob_order_id=data.order_id,
            amount=data.amount,
            currency=data.currency,
            status=data.status,
            tier=data.tier,
            created_at=datetime.utcnow()
        )
        db.add(payment_log)
        db.execute(
            text(
                """
                INSERT INTO user_credits (user_id, balance, updated_at)
                VALUES (:user_id, :credits, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE
                SET balance = user_credits.balance + EXCLUDED.balance,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {"user_id": str(data.user_id), "credits": PACKAGE_CREDITS[data.tier]},
        )
        db.execute(
            text(
                """
                INSERT INTO credit_transactions (user_id, amount, reason, created_at)
                VALUES (:user_id, :credits, :reason, CURRENT_TIMESTAMP)
                """
            ),
            {
                "user_id": str(data.user_id),
                "credits": PACKAGE_CREDITS[data.tier],
                "reason": f"paymob_{data.tier}",
            },
        )
        db.commit()
        logger.info(
            "Payment logged",
            extra={"order_id": data.order_id, "amount": data.amount, "tier": data.tier},
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