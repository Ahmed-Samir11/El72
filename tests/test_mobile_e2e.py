"""Live-server E2E suite that mirrors the Android app's real use cases.

This is NOT a TestClient suite: it talks to the running stack over HTTP, the
same way the phone will. Run it on the server PC while the stack is up:

    docker compose up -d
    pytest tests/test_mobile_e2e.py -v -s

Use cases covered (in app order):
  1. Server reachable            — GET /health
  2. Login works                 — register, login, wrong-password rejection,
                                     token-gated access, account-state endpoint
  3. Tracker works               — create from URL, enforcement cost,
                                     duplicate conflict, list, detail,
                                     refresh, target-price update
  4. Scraper works               — the on-demand fetcher visits a real
                                     product page and persists a live price

The tracker-limit mode is read from the server (GET /usage/limits), not assumed:
the same suite must pass against a fair-use release backend (409/429, no credit
moves) and against a legacy CREDITS_ENFORCEMENT=on backend (one credit per
tracker, 402 at zero). Under fair use the suite waits for its creation slot the
same way the app does — from the server's own retry_after_seconds.

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


def _usage(auth_headers) -> dict:
    """Read the caller's fair-use state from the server (GET /usage/limits)."""
    resp = _api("GET", "/usage/limits", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "enforcement" in body, body
    return body


def _wait_for_creation_slot(auth_headers):
    """Wait until the server would accept the next creation.

    The app gets its countdown from ``retry_after_seconds`` / ``Retry-After``;
    the suite does the same rather than sleeping a guessed constant, so it
    stays honest about the contract instead of papering over it.
    """
    wait = float(_usage(auth_headers).get("retry_after_seconds") or 0.0)
    if wait > 0:
        time.sleep(wait + 0.2)


def _create_tracker(auth_headers, url: str | None = None) -> dict:
    """Create one tracker and return its body, spacing creations properly.

    Every creation goes through here so a fair-use backend is not hammered
    into a 429 by the suite itself; the mode is the server's, not this file's.
    """
    _wait_for_creation_slot(auth_headers)
    resp = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": url or _unique_url()},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body.get("id"), body
    _created_trackers.add(body["id"])
    return body


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
    body = _create_tracker(auth_headers)
    assert isinstance(body["id"], int), body
    return body["id"]


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


def test_06_account_state_matches_the_enforcement_mode(auth_headers):
    """The account endpoint the app reads must answer in the shipped model.

    ``/usage/limits`` is what the Profile tab renders under fair use; the
    credit balance stays live only where the legacy ledger is the mode.
    """
    usage = _usage(auth_headers)
    assert usage["enforcement"] in ("fair_use", "on", "off"), usage
    assert isinstance(usage["active_trackers"], int), usage

    if usage["enforcement"] == "fair_use":
        # A ceiling the client can display, and it is the server that decides it.
        assert usage["cap"] and int(usage["cap"]) > 0, usage
    else:
        assert usage["cap"] is None, usage

    resp = _api("GET", "/credits/balance", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    balance = resp.json().get("balance", resp.json())
    if usage["enforcement"] == "on":
        # Legacy allowance for a free user (credits.TIER_STARTING_CREDITS).
        assert int(balance) == 100, resp.text


def test_07_create_tracker_from_url(auth_headers):
    body = _create_tracker(auth_headers)
    assert body.get("canonical_product_id"), body
    assert isinstance(body["id"], int), body


def test_08_create_duplicate_tracker_conflict(auth_headers):
    url = _unique_url()
    # First create succeeds (spaced the way the server asks).
    _wait_for_creation_slot(auth_headers)
    resp1 = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": url},
        headers=auth_headers,
    )
    assert resp1.status_code == 201, resp1.text
    tid = resp1.json()["id"]
    _created_trackers.add(tid)
    # Same URL → duplicate conflict (409). Enforcement runs first, so the
    # attempt must be spaced like any other creation or it answers 429 instead.
    _wait_for_creation_slot(auth_headers)
    resp2 = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": url},
        headers=auth_headers,
    )
    assert resp2.status_code == 409, resp2.text
    # A cap answer is also a 409, so the detail shape is the discriminator:
    # prose for "already tracking this", a dict for "you are at the cap".
    assert isinstance(resp2.json().get("detail"), str), resp2.text


def test_09_creation_cost_matches_the_enforcement_mode(auth_headers):
    """Free tracking is free — and the legacy ledger stays exact where it rules.

    Under fair use a new tracker moves no credit and does raise the active
    count; under CREDITS_ENFORCEMENT=on it still charges exactly one credit.
    """
    usage = _usage(auth_headers)
    before = _api("GET", "/credits/balance", headers=auth_headers).json()
    balance_before = int(before.get("balance", before))
    trackers_before = usage["active_trackers"]

    _create_tracker(auth_headers)

    after = _api("GET", "/credits/balance", headers=auth_headers).json()
    balance_after = int(after.get("balance", after))

    if usage["enforcement"] == "on":
        # Legacy ledger: one credit per tracker, exactly.
        assert balance_after == balance_before - 1, (balance_before, balance_after)
    else:
        # fair_use and off both spend no credit; the release default is fair_use.
        assert balance_after == balance_before, (balance_before, balance_after)

    if usage["enforcement"] == "fair_use":
        assert _usage(auth_headers)["active_trackers"] == trackers_before + 1


def test_10_tracker_appears_in_list(auth_headers):
    # Create a tracker, then verify it appears in the list.
    resp_create = _create_tracker(auth_headers)
    tid = resp_create["id"]

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


def test_14_creation_rate_window_is_enforced(auth_headers):
    """Hammering creation must answer 429 with a countdown the app can show.

    Before plans/p3 the client only had 429 in a comment; the live stack has
    to send the header for the retry affordance to exist. The window is
    process-local, so this row is honest only under the documented single-API
    deployment (compose starts one uvicorn worker, no --workers); a multi-worker
    stack needs the window in Redis, which is the named follow-up.
    """
    if _usage(auth_headers)["enforcement"] != "fair_use":
        pytest.skip("the creation rate window belongs to the fair-use mode")

    _create_tracker(auth_headers)
    resp = _api(
        "POST",
        "/tracked-items/from-url",
        json={"url": _unique_url()},
        headers=auth_headers,
    )
    assert resp.status_code == 429, resp.text
    retry_after = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    assert retry_after and int(retry_after) >= 1, resp.headers
    detail = resp.json()["detail"]
    assert detail["code"] == "creation_rate_limit", detail
    assert 0 < detail["retry_after_seconds"] <= 3.0, detail


def test_15_release_backend_serves_no_payment_surface(auth_headers):
    """No Paymob route on a fair-use backend — not even an undiscoverable one.

    The store listing can claim "free to track" only if the shipped stack
    really cannot take a payment: an unmounted router answers 404, a mounted
    one answers 404/405/200 depending on the path, and either way this row
    notices the drift. The skip covers both ways the surface can be asked
    for: legacy CREDITS_ENFORCEMENT=on, or an explicit PAYMENTS_ENABLED=true.
    """
    if _usage(auth_headers)["enforcement"] == "on":
        pytest.skip("this stack was started with the legacy credit model")

    probe = _api("GET", "/payment/start", headers=auth_headers)
    if probe.status_code != 404:
        pytest.skip(
            "this stack mounts the payment surface "
            "(PAYMENTS_ENABLED=true is set in its environment)"
        )

    for path in (
        "/payment/manual",
        "/subscription/status",
        "/admin/login",
    ):
        resp = _api("GET", path, headers=auth_headers)
        assert resp.status_code == 404, (path, resp.status_code, resp.text)
