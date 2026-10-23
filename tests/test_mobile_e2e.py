"""Live-server E2E suite that mirrors the Android app's real use cases.

This is NOT a TestClient suite: it talks to the running stack over HTTP, the
same way the phone will. Run it on the server PC while the stack is up:

    docker compose up -d
    pytest tests/test_mobile_e2e.py -v -s

Use cases covered (in app order):
  1. Server reachable            — GET /health
  2. Login works                 — register, login, wrong-password rejection,
                                     token-gated access, free-credit grant
  3. Tracker works               — create from URL, credit deduction,
                                     duplicate conflict, list, detail,
                                     refresh, target-price update
  4. Scraper works               — the on-demand fetcher visits a real
                                     product page and persists a live price

Environment overrides:
    API_BASE_URL        API base URL            (default http://127.0.0.1:8000)
    TEST_PRODUCT_URL    real product page       (default: stable Compumarts page)
    SCRAPER_TIMEOUT_SEC max wait for live fetch (default 180)
    TEST_PASSWORD       test user password      (default: testpass123 — local dev only)
"""

import os
import time
import uuid

import pytest
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TEST_PRODUCT_URL = os.getenv(
    "TEST_PRODUCT_URL",
    "https://www.compumarts.com/products/lenovo-legion-r27qe-gaming-monitor-"
    "27-inch-2560x1440-displayhdr-400-ips-panel-technology-200hz-refresh-rate-0-5ms-response-time",
)
SCRAPER_TIMEOUT_SEC = int(os.getenv("SCRAPER_TIMEOUT_SEC", "180"))
# Externalized password: set TEST_PASSWORD env var for anything beyond local
# dev. The fallback is intentionally insecure — never commit a real value.
PASSWORD = os.getenv("TEST_PASSWORD", "testpass123")
# States that mean the fetcher finished (one way or another).
TERMINAL_FETCH_STATUSES = {"ok", "no_price_found", "blocked", "fetch_failed"}

# Track created resources so the session teardown can clean them up.
_created_trackers: set = set()
_created_users: dict = {}  # phone -> access_token


def _phone() -> str:
    """Unique +20XXXXXXXXXX phone per run (13 chars, as the API requires)."""
    return f"+20{uuid.uuid4().int % 10**10:010d}"


def _unique_url() -> str:
    """TEST_PRODUCT_URL with a unique query suffix. The API's duplicate
    tracker check is global (any user tracking a URL blocks everyone else),
    so a fresh URL keeps each test independent. The store ignores unknown
    query params on product pages."""
    return f"{TEST_PRODUCT_URL}?el72_e2e={uuid.uuid4().hex[:8]}"


def _api(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE_URL}{path}"
    try:
        return requests.request(
            method, url, timeout=kwargs.pop("timeout", 60), **kwargs
        )
    except requests.exceptions.RequestException as exc:
        pytest.fail(
            f"API request failed: {method} {url} — {exc}. "
            "Start the stack first: Docker Desktop running, "
            "then `docker compose up -d`."
        )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def phone():
    """Unique phone number for the test."""
    return _phone()


@pytest.fixture
def auth_headers():
    """Register + log in a fresh user; return Bearer headers.

    Each test gets its own user so tests are fully independent — no shared
    module-level state, no execution-order dependence.
    """
    phone = _phone()
    resp = _api(
        "POST",
        "/auth/register",
        json={"phone": phone, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    _created_users[phone] = token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tracker_id(auth_headers):
    """Create a tracker from a unique URL; return its id."""
    resp = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": _unique_url()},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body.get("id"), body
    tid = body["id"]
    _created_trackers.add(tid)
    return tid


@pytest.fixture
def lowest_price(tracker_id, auth_headers):
    """Poll the detail endpoint until the on-demand fetch settles, then
    require a real live price. Returns the lowest_price dict."""
    deadline = time.time() + SCRAPER_TIMEOUT_SEC
    last = None
    while time.time() < deadline:
        resp = _api(
            "GET",
            f"/tracked-items/{tracker_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("fetch_status") in TERMINAL_FETCH_STATUSES:
            break
        time.sleep(5)

    assert last is not None, "no detail response received"
    status = last.get("fetch_status")
    assert (
        status in TERMINAL_FETCH_STATUSES
    ), f"Fetch did not settle within {SCRAPER_TIMEOUT_SEC}s; last state: {last}"
    assert status == "ok", (
        f"Scraper did not succeed: fetch_status={status!r}, "
        f"fetch_error={last.get('fetch_error')!r}. "
        "The phone would show a failed tracker. Check the API logs "
        "(docker compose logs api) and network access to the store."
    )
    lowest = last.get("lowest_price")
    assert lowest is not None, f"fetch_status=ok but no lowest_price: {last}"
    assert lowest["price_local"] > 0, lowest
    assert lowest["currency"], lowest
    return lowest


# --------------------------------------------------------------------------- #
# Teardown                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session", autouse=True)
def _teardown_session():
    """Delete every tracker and soft-delete every user created during the
    session so repeated runs don't accumulate test data."""
    yield
    for tid in _created_trackers:
        try:
            _api("DELETE", f"/tracked-items/{tid}")
        except Exception:
            pass
    for _phone, token in _created_users.items():
        try:
            _api(
                "DELETE",
                "/auth/me",
                headers=_auth(token),
            )
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
def test_01_api_health():
    resp = _api("GET", "/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "ok", body


def test_02_register_returns_token(phone):
    resp = _api(
        "POST",
        "/auth/register",
        json={"phone": phone, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("access_token"), body


def test_03_login_returns_token():
    # Register a fresh user, then log in with the same phone.
    phone = _phone()
    _api(
        "POST",
        "/auth/register",
        json={"phone": phone, "password": PASSWORD},
    )
    resp = _api(
        "POST",
        "/auth/login",
        json={"phone": phone, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token"), resp.text


def test_04_login_rejects_wrong_password():
    phone = _phone()
    _api(
        "POST",
        "/auth/register",
        json={"phone": phone, "password": PASSWORD},
    )
    resp = _api(
        "POST",
        "/auth/login",
        json={"phone": phone, "password": "wrongpassword99"},
    )
    assert resp.status_code == 401, resp.text


def test_05_protected_endpoint_requires_token(auth_headers):
    # The API rejects missing/invalid tokens with 401 or 403 depending on
    # the auth dependency path; either proves the endpoint is gated.
    without = _api("GET", "/credits/balance")
    assert without.status_code in (401, 403), without.text
    with_tok = _api("GET", "/credits/balance", headers=auth_headers)
    assert with_tok.status_code == 200, with_tok.text
    body = with_tok.json()
    assert "balance" in body or isinstance(body, int), body


def test_06_new_user_has_free_credits(auth_headers):
    resp = _api("GET", "/credits/balance", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    balance = body.get("balance", body)
    # Free allowance is 3 credits (one credit = one tracked item per week).
    assert int(balance) == 3, resp.text


def test_07_create_tracker_from_url(auth_headers):
    resp = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": _unique_url()},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body.get("id"), body
    assert body.get("canonical_product_id"), body
    assert isinstance(body["id"], int), body


def test_08_create_duplicate_tracker_conflict(auth_headers):
    url = _unique_url()
    # First create succeeds.
    resp1 = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": url},
        headers=auth_headers,
    )
    assert resp1.status_code == 201, resp1.text
    tid = resp1.json()["id"]
    _created_trackers.add(tid)
    # Same URL → duplicate conflict (409).
    resp2 = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": url},
        headers=auth_headers,
    )
    assert resp2.status_code == 409, resp2.text


def test_09_tracker_deducted_a_credit(auth_headers):
    # Creating a tracker deducts 1 credit: 3 -> 2.
    _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": _unique_url()},
        headers=auth_headers,
    )
    resp = _api("GET", "/credits/balance", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    balance = resp.json().get("balance", resp.json())
    assert int(balance) == 2, resp.text


def test_10_tracker_appears_in_list(auth_headers):
    # Create a tracker, then verify it appears in the list.
    resp_create = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": _unique_url()},
        headers=auth_headers,
    )
    assert resp_create.status_code == 201, resp_create.text
    tid = resp_create.json()["id"]
    _created_trackers.add(tid)

    resp_list = _api("GET", "/tracked-items", headers=auth_headers)
    assert resp_list.status_code == 200, resp_list.text
    items = resp_list.json()
    assert isinstance(items, list), resp_list.text
    assert tid in [item.get("id") for item in items], resp_list.text


def test_11_scraper_fetches_live_price(tracker_id, auth_headers, lowest_price):
    # The `lowest_price` fixture already verified a live price was fetched.
    # This test asserts the detail endpoint consistently returns the settled
    # state with the expected schema.
    resp = _api(
        "GET",
        f"/tracked-items/{tracker_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail.get("id") == tracker_id, detail
    assert detail.get("fetch_status") in TERMINAL_FETCH_STATUSES, detail
    lowest = detail.get("lowest_price")
    assert lowest is not None, detail
    assert lowest["price_local"] > 0, lowest
    assert lowest["currency"], lowest


def test_12_refresh_endpoint(tracker_id, auth_headers):
    # 200 = fresh fetch triggered; 429 = throttled. Both prove the endpoint
    # is alive; anything else is a bug.
    resp = _api(
        "POST",
        f"/tracked-items/{tracker_id}/refresh",
        headers=auth_headers,
    )
    assert resp.status_code in (200, 429), resp.text


def test_13_update_target_price(tracker_id, lowest_price, auth_headers):
    # Set the target above the live price: the app's deal-alert condition.
    # Note: the API takes target_price as a query parameter, not a JSON body.
    target = round(lowest_price["price_local"] * 1.5, 2)
    resp = _api(
        "PATCH",
        f"/tracked-items/{tracker_id}/target-price",
        params={"target_price": target},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    detail = _api(
        "GET",
        f"/tracked-items/{tracker_id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json().get("target_price") == target, detail.text
