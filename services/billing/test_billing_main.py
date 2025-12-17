import os
os.environ["DATABASE_URL"] = "sqlite:///test.db"

import pytest
from fastapi.testclient import TestClient
from services.billing.main import app

client = TestClient(app)

def test_get_pricing():
    response = client.get("/pricing")
    assert response.status_code == 200
    data = response.json()
    assert "free" in data
    assert "premium" in data
    assert "enterprise" in data
    assert data["free"]["price"] == 0

def test_paymob_webhook_success():
    from services.billing.models import Base
    from services.billing.main import engine as app_engine
    Base.metadata.create_all(bind=app_engine)
    
    payload = {
        "order_id": "test123",
        "amount": 100.0,
        "currency": "EGP",
        "status": "success",
        "user_id": 1,
        "tier": "premium",
        "valid_days": 30
    }
    response = client.post("/webhook/paymob", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "processed"}

def test_paymob_webhook_invalid_status():
    payload = {
        "order_id": "test124",
        "amount": 50.0,
        "currency": "EGP",
        "status": "failed",
        "user_id": 1,
        "tier": "free",
        "valid_days": 0
    }
    response = client.post("/webhook/paymob", json=payload)
    assert response.status_code == 200
    # Should still process, but not log payment
    assert response.json() == {"status": "processed"}