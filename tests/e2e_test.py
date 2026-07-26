import os
import sys
from pathlib import Path

if os.path.exists("test_e2e.db"):
    os.remove("test_e2e.db")

os.environ["DATABASE_URL"] = "sqlite:///./test_e2e.db"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SECRET_KEY", "test-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.api import main as api_main


api_main.Base.metadata.create_all(bind=api_main.engine)
client = TestClient(api_main.app)


def test_user_loop(monkeypatch):
    monkeypatch.setattr(api_main, "push_to_stream", AsyncMock(return_value=None))
    phone = f"+20{uuid.uuid4().int % 10**10:010d}"

    register_resp = client.post(
        "/auth/register",
        json={
            "phone": phone,
            "password": "testpass123",
        },
    )
    assert register_resp.status_code == 200

    token = register_resp.json()["access_token"]
    assert token

    alert_resp = client.post(
        "/alerts",
        json={
            "target_url": "https://example.com/test",
            "target_price": 50.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert alert_resp.status_code == 200
    assert "id" in alert_resp.json()
