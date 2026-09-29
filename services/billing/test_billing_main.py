import hashlib
import hmac
import json
import os
import uuid

# Use a distinct SQLite file so this module does not clash with the API
# tests (which use test.db); on Windows an open file cannot be removed.
os.environ["DATABASE_URL"] = "sqlite:///billing_test.db"
os.environ["PAYMOB_HMAC_SECRET"] = "test-secret"
if os.path.exists("billing_test.db"):
    os.remove("billing_test.db")

from fastapi.testclient import TestClient
from sqlalchemy import text

from services.billing.main import app

client = TestClient(app)


def test_get_pricing():
    response = client.get("/pricing")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "EGP"
    assert data["packages"]["free"]["credits"] == 3
    assert data["packages"]["standard"]["credits"] == 10
    assert data["packages"]["premium"]["credits"] == 30


def _signed_request(payload):
    body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(b"test-secret", body, hashlib.sha512).hexdigest()
    return body, {"X-Paymob-Signature": signature}


def test_paymob_webhook_success():
    from services.billing.main import engine as app_engine
    from services.billing.models import Base

    Base.metadata.create_all(bind=app_engine)

    user_id = str(uuid.uuid4())
    with app_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS user_credits "
                "(user_id TEXT PRIMARY KEY, balance INTEGER NOT NULL, "
                "updated_at TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS credit_transactions "
                "(id TEXT PRIMARY KEY, user_id TEXT, amount INTEGER, "
                "reason TEXT, created_at TIMESTAMP)"
            )
        )
    payload = {
        "order_id": f"test-{uuid.uuid4()}",
        "amount": 90.0,
        "currency": "EGP",
        "status": "success",
        "user_id": user_id,
        "tier": "premium",
    }
    body, headers = _signed_request(payload)
    response = client.post("/webhook/paymob", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "processed"}


def test_paymob_webhook_invalid_status():
    payload = {
        "order_id": "test124",
        "amount": 50.0,
        "currency": "EGP",
        "status": "failed",
        "user_id": str(uuid.uuid4()),
        "tier": "free",
    }
    body, headers = _signed_request(payload)
    response = client.post("/webhook/paymob", content=body, headers=headers)
    assert response.status_code == 200
    # Should still process, but not log payment
    assert response.json() == {"status": "processed"}


def test_paymob_webhook_rejects_unsigned_payload():
    payload = {
        "order_id": "unsigned",
        "amount": 30.0,
        "currency": "EGP",
        "status": "success",
        "user_id": 1,
        "tier": "standard",
    }
    response = client.post("/webhook/paymob", json=payload)
    assert response.status_code == 401
