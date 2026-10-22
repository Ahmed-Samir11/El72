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
"""

import os
import time
import uuid

import pytest
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
# A unique query suffix per run: the API's duplicate-tracker check is global
# (any user tracking a URL blocks everyone else), so a fresh URL keeps each
# run independent. The store ignores unknown query params on product pages.
TEST_PRODUCT_URL = os.getenv(
    "TEST_PRODUCT_URL",
    "https://www.compumarts.com/products/lenovo-legion-r27qe-gaming-monitor-"
    "27-inch-2560x1440-displayhdr-400-ips-panel-technology-200hz-refresh-rate-0-5ms-response-time"
    f"?el72_e2e={uuid.uuid4().hex[:8]}",
)
SCRAPER_TIMEOUT_SEC = int(os.getenv("SCRAPER_TIMEOUT_SEC", "180"))

PASSWORD = "testpass123"
# States that mean the fetcher finished (one way or another).
TERMINAL_FETCH_STATUSES = {"ok", "no_price_found", "blocked", "fetch_failed"}

# Module-level state shared by the ordered tests below (one user, one
# tracker — the same session a phone user would have).
STATE: dict = {}


def _phone() -> str:
    """Unique +20XXXXXXXXXX phone per run (13 chars, as the API requires)."""
    return f"+20{uuid.uuid4().int % 10**10:010d}"


def _api(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE_URL}{path}"
    try:
        return requests.request(
            method, url, timeout=kwargs.pop("timeout", 60), **kwargs
        )
    except requests.exceptions.ConnectionError:
        pytest.fail(
            f"Cannot reach the API at {url}. "
            "Start the stack first: Docker Desktop running, "
            "then `docker compose up -d`."
        )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# 1. Server reachable                                                          #
# --------------------------------------------------------------------------- #
def test_01_api_health():
    resp = _api("GET", "/health")
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 2. Login works                                                               #
# --------------------------------------------------------------------------- #
def test_02_register_returns_token():
    phone = _phone()
    resp = _api(
        "POST",
        "/auth/register",
        json={"phone": phone, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("access_token"), body
    STATE["phone"] = phone
    STATE["token"] = body["access_token"]


def test_03_login_returns_token():
    resp = _api(
        "POST",
        "/auth/login",
        json={"phone": STATE["phone"], "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token"), resp.text


def test_04_login_rejects_wrong_password():
    resp = _api(
        "POST",
        "/auth/login",
        json={"phone": STATE["phone"], "password": "wrongpassword99"},
    )
    assert resp.status_code == 401, resp.text


def test_05_protected_endpoint_requires_token():
    # The API rejects missing/invalid tokens with 401 or 403 depending on
    # the auth dependency path; either proves the endpoint is gated.
    without = _api("GET", "/credits/balance")
    assert without.status_code in (401, 403), without.text
    with_tok = _api("GET", "/credits/balance", headers=_auth(STATE["token"]))
    assert with_tok.status_code == 200, with_tok.text


def test_06_new_user_has_free_credits():
    resp = _api("GET", "/credits/balance", headers=_auth(STATE["token"]))
    assert resp.status_code == 200, resp.text
    balance = resp.json().get("balance", resp.json())
    # Free allowance is 3 credits (one credit = one tracked item per week).
    assert int(balance) == 3, resp.text


# --------------------------------------------------------------------------- #
# 3. Tracker works                                                              #
# --------------------------------------------------------------------------- #
def test_07_create_tracker_from_url():
    resp = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": TEST_PRODUCT_URL},
        headers=_auth(STATE["token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body.get("id"), body
    STATE["tracker_id"] = body["id"]
    assert body.get("canonical_product_id"), body


def test_08_create_duplicate_tracker_conflict():
    resp = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": TEST_PRODUCT_URL},
        headers=_auth(STATE["token"]),
    )
    assert resp.status_code == 409, resp.text


def test_09_tracker_deducted_a_credit():
    resp = _api("GET", "/credits/balance", headers=_auth(STATE["token"]))
    assert resp.status_code == 200, resp.text
    balance = resp.json().get("balance", resp.json())
    assert int(balance) == 2, resp.text


def test_10_tracker_appears_in_list():
    resp = _api("GET", "/tracked-items", headers=_auth(STATE["token"]))
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert isinstance(items, list), resp.text
    assert STATE["tracker_id"] in [item.get("id") for item in items], resp.text


def test_11_scraper_fetches_live_price():
    """The core 'does the scraper work?' check.

    The create request triggers a background fetch of the real product page.
    Poll the detail endpoint until the fetch settles, then require a real
    price — a bot-wall or fetch failure here means the phone would show a
    dead tracker.
    """
    deadline = time.time() + SCRAPER_TIMEOUT_SEC
    last = None
    while time.time() < deadline:
        resp = _api(
            "GET",
            f"/tracked-items/{STATE['tracker_id']}",
            headers=_auth(STATE["token"]),
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
    STATE["lowest_price"] = lowest["price_local"]


def test_12_refresh_endpoint():
    # 200 = fresh fetch triggered; 429 = throttled because the create-time
    # fetch is still inside its one-minute window. Both prove the endpoint
    # is alive; anything else is a bug.
    resp = _api(
        "POST",
        f"/tracked-items/{STATE['tracker_id']}/refresh",
        headers=_auth(STATE["token"]),
    )
    assert resp.status_code in (200, 429), resp.text


def test_13_update_target_price():
    # Set the target above the live price: the app's deal-alert condition.
    # Note: the API takes target_price as a query parameter, not a JSON body.
    target = round(STATE["lowest_price"] * 1.5, 2)
    resp = _api(
        "PATCH",
        f"/tracked-items/{STATE['tracker_id']}/target-price",
        params={"target_price": target},
        headers=_auth(STATE["token"]),
    )
    assert resp.status_code == 200, resp.text
    detail = _api(
        "GET",
        f"/tracked-items/{STATE['tracker_id']}",
        headers=_auth(STATE["token"]),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json().get("target_price") == target, detail.text
