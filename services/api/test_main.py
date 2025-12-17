import os
os.environ["DATABASE_URL"] = "sqlite:///test.db"

if os.path.exists("test.db"):
    os.remove("test.db")

import pytest
from fastapi.testclient import TestClient
from services.api.main import app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from services.api.models import Base

# In-memory SQLite for testing
engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from services.api.main import engine as app_engine
Base.metadata.create_all(bind=app_engine)

client = TestClient(app)

def test_register_user():
    payload = {"phone": "+201234567890", "password": "password123"}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_register_duplicate_user():
    payload = {"phone": "+201234567891", "password": "password123"}
    client.post("/auth/register", json=payload)  # First register
    response = client.post("/auth/register", json=payload)  # Duplicate
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]

def test_create_alert():
    # First register and get token
    payload = {"phone": "+201234567892", "password": "password123"}
    response = client.post("/auth/register", json=payload)
    token = response.json()["access_token"]

    # Create alert
    alert_payload = {"target_url": "https://example.com/product", "target_price": 100.0}
    response = client.post("/alerts", json=alert_payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "Alert created" in data["message"]