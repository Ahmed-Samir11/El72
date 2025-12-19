import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from services.billing.models import Base, PaymentLog
# from services.common.redis_client import RedisStreamClient

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost/elhaq")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PAYMOB_HMAC_SECRET = os.getenv("PAYMOB_HMAC_SECRET", "your-hmac-secret")

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
    user_id: int  # Assuming Paymob includes user_id
    tier: str
    valid_days: int

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_paymob_webhook(request: Request, body: bytes) -> bool:
    # Implement HMAC verification
    # For MVP, skip or mock
    return True

@app.post("/webhook/paymob")
async def paymob_webhook(request: Request, db: Session = Depends(get_db)):
    import json
    body = await request.body()
    if not verify_paymob_webhook(request, body):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse webhook data
    try:
        data_dict = json.loads(body.decode('utf-8'))
        data = PaymentWebhook(**data_dict)
    except Exception:
        # Mock for now if parsing fails
        data = PaymentWebhook(
            order_id="12345",
            amount=100.0,
            currency="EGP",
            status="success",
            user_id=1,
            tier="premium",
            valid_days=30
        )

    if data.status == "success":
        # Log payment
        valid_until = datetime.utcnow() + timedelta(days=data.valid_days)
        payment_log = PaymentLog(
            user_id=data.user_id,
            paymob_order_id=data.order_id,
            amount=data.amount,
            currency=data.currency,
            status=data.status,
            tier=data.tier,
            valid_until=valid_until,
            created_at=datetime.utcnow()
        )
        db.add(payment_log)
        db.commit()
        print(f"Payment logged: {data.order_id}, amount {data.amount}, tier {data.tier}")

    return {"status": "processed"}

@app.get("/pricing")
def get_dynamic_pricing():
    # Mock dynamic pricing based on demand
    # In real, query analytics
    return {
        "basic": {"alerts": 10, "price": 100},
        "plus": {"alerts": 50, "price": 250},
        "pro": {"alerts": 200, "price": 500}
    }