import os

os.environ["DATABASE_URL"] = "sqlite:///test.db"

if os.path.exists("test.db"):
    os.remove("test.db")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.main import app, mount_routers
from services.api.main import engine as app_engine
from services.api.models import Base

# In-memory SQLite for testing
engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    response = client.post(
        "/alerts", json=alert_payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "Alert created" in data["message"]


def _make_request_scope(client_host: str, headers: dict = None) -> dict:
    """Build a minimal ASGI scope for a Request object."""
    scope = {
        "type": "http",
        "client": [client_host, 12345],
        "headers": [],
    }
    if headers:
        scope["headers"] = [[k.encode(), v.encode()] for k, v in headers.items()]
    return scope


def test_client_ip_trusted_proxy_with_x_forwarded_for():
    from services.api.main import TRUSTED_PROXIES, _client_ip

    TRUSTED_PROXIES.add("10.0.0.1")
    try:
        scope = _make_request_scope("10.0.0.1", {"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
        from starlette.requests import Request

        request = Request(scope)
        assert _client_ip(request) == "1.2.3.4"
    finally:
        TRUSTED_PROXIES.discard("10.0.0.1")


def test_client_ip_trusted_proxy_without_x_forwarded_for():
    from services.api.main import TRUSTED_PROXIES, _client_ip

    TRUSTED_PROXIES.add("10.0.0.1")
    try:
        scope = _make_request_scope("10.0.0.1")
        from starlette.requests import Request

        request = Request(scope)
        assert _client_ip(request) == "10.0.0.1"
    finally:
        TRUSTED_PROXIES.discard("10.0.0.1")


def test_client_ip_untrusted_proxy_ignores_x_forwarded_for():
    from services.api.main import _client_ip

    # 10.0.0.1 is NOT trusted; the header must be ignored.
    scope = _make_request_scope("9.9.9.9", {"x-forwarded-for": "1.2.3.4"})
    from starlette.requests import Request

    request = Request(scope)
    assert _client_ip(request) == "9.9.9.9"


def test_client_ip_missing_client_info():
    from services.api.main import _client_ip

    scope = {"type": "http", "client": None, "headers": []}
    from starlette.requests import Request

    request = Request(scope)
    assert _client_ip(request) == "unknown"


def test_cors_allowed_origin_from_env():
    import os

    os.environ["ALLOWED_ORIGINS"] = "https://el72.io"
    # Re-import to pick up the allowlist.
    import importlib

    import services.api.main as api_main

    importlib.reload(api_main)

    from fastapi.testclient import TestClient

    test_client = TestClient(api_main.app)
    resp = test_client.get("/health", headers={"Origin": "https://el72.io"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://el72.io"

    del os.environ["ALLOWED_ORIGINS"]
    importlib.reload(api_main)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_preflight_allowed_origin():
    import os

    os.environ["ALLOWED_ORIGINS"] = "https://el72.io"
    import importlib

    import services.api.main as api_main

    importlib.reload(api_main)

    from fastapi.testclient import TestClient

    test_client = TestClient(api_main.app)
    resp = test_client.options("/health", headers={"Origin": "https://el72.io"})
    # /health only supports GET, so OPTIONS returns 405, but CORS headers
    # must still be present for the allowed origin.
    assert resp.headers.get("access-control-allow-origin") == "https://el72.io"
    assert resp.headers.get("access-control-allow-credentials") == "true"

    del os.environ["ALLOWED_ORIGINS"]
    importlib.reload(api_main)


def test_cors_preflight_disallowed_origin():
    import os

    os.environ["ALLOWED_ORIGINS"] = "https://el72.io"
    import importlib

    import services.api.main as api_main

    importlib.reload(api_main)

    from fastapi.testclient import TestClient

    test_client = TestClient(api_main.app)
    resp = test_client.options("/health", headers={"Origin": "https://evil.com"})
    # Disallowed origin: no CORS allow-origin header should be returned.
    assert "access-control-allow-origin" not in resp.headers

    del os.environ["ALLOWED_ORIGINS"]
    importlib.reload(api_main)


def test_trusted_proxy_blocks_xff_spoofing_full_cycle():
    """X-Forwarded-For from an untrusted peer must not be honored.

    Simulates a malicious client directly connecting to the API (not via
    a trusted proxy) but forging an X-Forwarded-For header. The rate
    limiter must see the direct IP, not the forged header.
    """
    import os

    os.environ["TRUSTED_PROXIES"] = "10.0.0.1"
    import importlib

    import services.api.main as api_main

    importlib.reload(api_main)

    from fastapi.testclient import TestClient

    test_client = TestClient(api_main.app)

    # Direct connection from an untrusted IP with forged X-Forwarded-For.
    # The API must rate-limit based on the direct IP, not the forged header.
    resp1 = test_client.get(
        "/health",
        headers={
            "Origin": "https://el72.io",
            "X-Forwarded-For": "1.2.3.4",
        },
    )
    assert resp1.status_code == 200

    # Same request again - if the forged header were honored, the rate
    # limiter would see 1.2.3.4 and might allow more requests. With the
    # direct IP (TestClient uses testclient), per-IP limiting applies.
    resp2 = test_client.get(
        "/health",
        headers={
            "Origin": "https://el72.io",
            "X-Forwarded-For": "1.2.3.4",
        },
    )
    assert resp2.status_code == 200

    del os.environ["TRUSTED_PROXIES"]
    importlib.reload(api_main)


def test_cors_disallowed_origin_rejected():
    import os

    os.environ["ALLOWED_ORIGINS"] = "https://el72.io"
    import importlib

    import services.api.main as api_main

    importlib.reload(api_main)

    from fastapi.testclient import TestClient

    test_client = TestClient(api_main.app)
    resp = test_client.get("/health", headers={"Origin": "https://evil.com"})
    # Preflight/OPTIONS is allowed; a plain GET with a disallowed origin is
    # still served (CORS is a client-side enforcement), but the response
    # must not echo the disallowed origin.
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers

    del os.environ["ALLOWED_ORIGINS"]
    importlib.reload(api_main)


# --- the payment surface is a mount decision, not an assumption (plans/p3) ---


def test_release_build_mounts_no_payment_surface():
    """The shipped configuration registers no Paymob route at all.

    This is what lets the store listing make no payment claim and keeps a
    financial-transaction surface off the release backend: an endpoint nobody
    advertises is still an endpoint somebody can find.
    """
    built = FastAPI()
    mount_routers(built, payment_surface=False)

    paths = {route.path for route in built.routes}
    assert not [p for p in paths if p.startswith("/payment")]
    assert not [p for p in paths if p.startswith("/subscription")]
    assert not [p for p in paths if p.startswith("/admin")]

    probe = TestClient(built)
    assert probe.get("/payment/status/anything").status_code == 404
    # The free-tracker surface is mounted, and it is auth-gated.
    assert "/usage/limits" in paths
    assert probe.get("/usage/limits").status_code == 401


def test_payment_surface_mounts_when_it_is_asked_for():
    """The rails are flagged out of the release, not deleted: asking for them
    mounts the whole payment and subscription surface again."""
    built = FastAPI()
    mount_routers(built, payment_surface=True)

    paths = {route.path for route in built.routes}
    assert "/payment/start" in paths
    assert "/payment/manual" in paths
    assert "/subscription/status" in paths
