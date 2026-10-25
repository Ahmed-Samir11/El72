"""Unit tests for the chatbot service.

Tests cover:
* Health endpoint
* Session listing (with auth)
* Session retrieval (with auth + ownership)
* Add-to-feed with URL and 402 handling
* Intent parsing
"""

import os

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.chatbot.main import (
    app,
    get_authenticated_user_id,
    get_db,
    verify_jwt_token,
)
from services.chatbot.search_service import (
    STORES,
    ChatbotSearchService,
    parse_intent,
)

# ---------------------------------------------------------------------------
# Test database (SQLite — UUID stored as TEXT for test compatibility)
# ---------------------------------------------------------------------------

TEST_DB_PATH = "test_chatbot.db"
TEST_ENGINE = create_engine(f"sqlite:///{TEST_DB_PATH}")
TEST_SESSION_LOCAL = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)

# JWT test settings
TEST_SECRET_KEY = "test-secret-key-for-tests"
TEST_ALGORITHM = "HS256"


def _make_token(phone: str) -> str:
    """Create a JWT token with the given phone number as sub."""
    import datetime

    payload = {
        "sub": phone,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
    }
    return jwt.encode(payload, TEST_SECRET_KEY, algorithm=TEST_ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Create a test client with the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    """Create a fresh database session with chat tables for each test."""
    db = TEST_SESSION_LOCAL()
    try:
        # Drop and recreate chat tables
        db.execute(text("DROP TABLE IF EXISTS chat_search_results"))
        db.execute(text("DROP TABLE IF EXISTS chat_messages"))
        db.execute(text("DROP TABLE IF EXISTS chat_sessions"))
        db.commit()

        # Create chat tables (UUID as TEXT for SQLite compatibility)
        db.execute(
            text(
                "CREATE TABLE chat_sessions ("
                "id TEXT PRIMARY KEY, "
                "user_id INTEGER NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE chat_messages ("
                "id TEXT PRIMARY KEY, "
                "session_id TEXT NOT NULL, "
                "role VARCHAR(10) NOT NULL, "
                "content TEXT NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE chat_search_results ("
                "id TEXT PRIMARY KEY, "
                "session_id TEXT NOT NULL, "
                "store_id TEXT NOT NULL, "
                "product_title TEXT NOT NULL, "
                "price_local NUMERIC(10, 2) NOT NULL, "
                "currency TEXT NOT NULL DEFAULT 'EGP', "
                "url TEXT NOT NULL, "
                "image_url TEXT, "
                "position INTEGER NOT NULL DEFAULT 0, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        db.commit()
        yield db
    finally:
        try:
            db.close()
        except Exception:
            pass


@pytest.fixture
def override_db(db_session):
    """Override the get_db dependency with a test session."""
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def override_auth():
    """Override JWT auth dependencies to return a fixed user_id.

    We override verify_jwt_token to return a valid payload and
    get_authenticated_user_id to return a fixed user_id (1) without hitting
    the database.
    """
    app.dependency_overrides[verify_jwt_token] = lambda: {"sub": "+201234567890"}
    app.dependency_overrides[get_authenticated_user_id] = lambda: 1
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Return Bearer headers with a valid JWT token."""
    token = _make_token("+201234567890")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_endpoint(client):
    """Test the health endpoint returns 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "chatbot"


def test_list_sessions_requires_auth(client, override_db):
    """Test listing sessions without auth returns 401."""
    response = client.get("/chatbot/sessions")
    assert response.status_code == 401


def test_list_sessions_with_auth(client, override_db, override_auth):
    """Test listing sessions with valid auth returns 200."""
    response = client.get("/chatbot/sessions")
    assert response.status_code == 200
    assert response.json() == []


def test_get_session_requires_auth(client, override_db):
    """Test getting a session without auth returns 401."""
    response = client.get("/chatbot/sessions/999")
    assert response.status_code == 401


def test_get_session_not_found(client, override_db, override_auth):
    """Test getting a non-existent session returns 404."""
    # Use a valid UUID format that doesn't exist in the database
    response = client.get("/chatbot/sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_get_session_ownership(client, override_db, override_auth, db_session):
    """Test that a user cannot access another user's session.

    We create a session for user_id=1 (the authenticated user) and then
    try to access it with a different authenticated user_id.
    """
    # Override auth to return user_id=2 for this test
    app.dependency_overrides[get_authenticated_user_id] = lambda: 2

    # Create a session for user_id=1 directly in the DB
    import uuid as _uuid

    session_id = str(_uuid.uuid4())
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": session_id, "user_id": 1},
    )
    db_session.commit()

    # Try to access it as user_id=2 (should fail - ownership check)
    response = client.get(f"/chatbot/sessions/{session_id}")
    assert response.status_code == 404

    # Restore the override
    app.dependency_overrides[get_authenticated_user_id] = lambda: 1


def test_send_message_requires_auth(client, override_db):
    """Test sending a message without auth returns 401."""
    response = client.post(
        "/chatbot/message",
        json={"message": "test query"},
    )
    assert response.status_code == 401


def test_parse_intent_with_price_filter():
    """Test intent parsing extracts price filter correctly."""
    result = parse_intent("gaming laptop under 50000 EGP")
    assert result["query"] == "gaming laptop"
    assert result["max_price"] == 50000.0


def test_parse_intent_without_price():
    """Test intent parsing without price filter."""
    result = parse_intent("iPhone 15 Pro Max")
    assert result["query"] == "iPhone 15 Pro Max"
    assert result["max_price"] is None


def test_parse_intent_below_price():
    """Test intent parsing with 'below' keyword."""
    result = parse_intent("Samsung TV below 30000")
    assert result["query"] == "Samsung TV"
    assert result["max_price"] == 30000.0


def test_parse_intent_max_price():
    """Test intent parsing with 'max' keyword."""
    result = parse_intent("laptop max 40000")
    assert result["query"] == "laptop"
    assert result["max_price"] == 40000.0


def test_stores_configured():
    """Test that stores are configured."""
    assert len(STORES) > 0
    store_ids = [s.store_id for s in STORES]
    assert "amazon_eg" in store_ids
    assert "noon" in store_ids
    assert "jumia" in store_ids


@pytest.mark.asyncio
async def test_search_service_init():
    """Test that the search service initializes correctly."""
    service = ChatbotSearchService()
    assert service.stores == STORES
    await service.close()


# ---------------------------------------------------------------------------
# Add-to-feed tests
# ---------------------------------------------------------------------------


def test_add_to_feed_with_url(
    client, override_db, override_auth, db_session, auth_headers
):
    """Test add-to-feed with a specific URL creates a tracker.

    Mocks the API service to return success.
    """
    # Create a session and a search result
    import uuid as _uuid

    import httpx

    session_id = str(_uuid.uuid4())
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": session_id, "user_id": 1},
    )
    db_session.execute(
        text(
            "INSERT INTO chat_search_results "
            "(session_id, store_id, product_title, price_local, currency, url) "
            "VALUES (:sid, :store_id, :title, :price, :currency, :url)",
        ),
        {
            "sid": session_id,
            "store_id": "amazon_eg",
            "title": "Test Product",
            "price": 100.0,
            "currency": "EGP",
            "url": "https://example.com/product",
        },
    )
    db_session.commit()

    # Mock the API service
    class MockResponse:
        status_code = 200

        def json(self):
            return {"message": "Tracker created successfully"}

        def raise_for_status(self):
            pass

    original_post = httpx.AsyncClient.post

    async def mock_post(self, url, **kwargs):
        if "/tracked-items/from-url" in url:
            return MockResponse()
        return original_post(self, url, **kwargs)

    httpx.AsyncClient.post = mock_post
    try:
        response = client.post(
            "/chatbot/add-to-feed",
            json={
                "session_id": session_id,
                "product_url": "https://example.com/product",
            },
            headers=auth_headers,
        )
    finally:
        httpx.AsyncClient.post = original_post

    assert response.status_code == 200
    data = response.json()
    assert "added" in data["message"].lower() or "tracker" in data["message"].lower()


def test_add_to_feed_insufficient_credits(
    client, override_db, override_auth, db_session, auth_headers
):
    """Test add-to-feed when the API returns 402 (insufficient credits)."""
    # Create a session and a search result
    import uuid as _uuid

    import httpx

    session_id = str(_uuid.uuid4())
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": session_id, "user_id": 1},
    )
    db_session.execute(
        text(
            "INSERT INTO chat_search_results "
            "(session_id, store_id, product_title, price_local, currency, url) "
            "VALUES (:sid, :store_id, :title, :price, :currency, :url)",
        ),
        {
            "sid": session_id,
            "store_id": "amazon_eg",
            "title": "Test Product",
            "price": 100.0,
            "currency": "EGP",
            "url": "https://example.com/product",
        },
    )
    db_session.commit()

    # Mock the API service to return 402
    class MockResponse:
        status_code = 402

        def json(self):
            return {"detail": "Insufficient credits"}

        def raise_for_status(self):
            pass

    original_post = httpx.AsyncClient.post

    async def mock_post(self, url, **kwargs):
        if "/tracked-items/from-url" in url:
            return MockResponse()
        return original_post(self, url, **kwargs)

    httpx.AsyncClient.post = mock_post
    try:
        response = client.post(
            "/chatbot/add-to-feed",
            json={
                "session_id": session_id,
                "product_url": "https://example.com/product",
            },
            headers=auth_headers,
        )
    finally:
        httpx.AsyncClient.post = original_post

    assert response.status_code == 200
    data = response.json()
    msg = data["message"].lower()
    assert "credit" in msg or "insufficient" in msg


def test_add_to_feed_no_results(
    client, override_db, override_auth, db_session, auth_headers
):
    """Test add-to-feed when there are no search results."""
    import uuid as _uuid

    session_id = str(_uuid.uuid4())
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": session_id, "user_id": 1},
    )
    db_session.commit()

    response = client.post(
        "/chatbot/add-to-feed",
        json={
            "session_id": session_id,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "no search results" in data["message"].lower()


# ---------------------------------------------------------------------------
# Speed PR: result ids, store status, rate-limit keys
# ---------------------------------------------------------------------------


def _capture_add_posts(monkeypatch):
    """Record the URL the chatbot asks the API service to track."""
    import httpx

    posted = []
    original_post = httpx.AsyncClient.post

    class MockResponse:
        status_code = 200

        def json(self):
            return {"message": "Tracker created successfully"}

        def raise_for_status(self):
            pass

    async def mock_post(self, url, **kwargs):
        if "/tracked-items/from-url" in url:
            posted.append(kwargs.get("json", {}).get("url"))
            return MockResponse()
        return original_post(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    return posted


def test_add_to_feed_by_result_id(
    client, override_db, override_auth, db_session, auth_headers, monkeypatch
):
    """A result_id adds exactly that product, not merely the newest row."""
    import uuid as _uuid

    posted = _capture_add_posts(monkeypatch)

    session_id = str(_uuid.uuid4())
    first_id = _uuid.uuid4()
    second_id = _uuid.uuid4()
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": session_id, "user_id": 1},
    )
    for row_id, position, url in (
        (first_id, 0, "https://example.com/first"),
        (second_id, 1, "https://example.com/second"),
    ):
        db_session.execute(
            text(
                "INSERT INTO chat_search_results "
                "(id, session_id, store_id, product_title, price_local, "
                "currency, url, position) "
                "VALUES (:id, :sid, :store_id, :title, :price, :currency, :url, "
                ":position)"
            ),
            {
                "id": str(row_id),
                "sid": session_id,
                "store_id": "amazon_eg",
                "title": f"Product {position}",
                "price": 100.0 + position,
                "currency": "EGP",
                "url": url,
                "position": position,
            },
        )
    db_session.commit()

    response = client.post(
        "/chatbot/add-to-feed",
        json={"session_id": session_id, "result_id": str(second_id)},
        headers=auth_headers,
    )

    assert response.status_code == 200
    # The confirmation names the product the result_id pointed at.
    assert "Product 1" in response.json()["message"]
    assert posted == ["https://example.com/second"]


def test_a_result_id_must_belong_to_the_session_that_asks(
    client, override_db, override_auth, db_session, auth_headers, monkeypatch
):
    """Another session's row id addresses nothing here.

    Searches are saved per session, so the lookup is scoped by session_id: a
    foreign id (or a forged one) must not track someone else's product, and
    cached payloads must not smuggle one in either.
    """
    import uuid as _uuid

    posted = _capture_add_posts(monkeypatch)

    owner, intruder = str(_uuid.uuid4()), str(_uuid.uuid4())
    for sid in (owner, intruder):
        db_session.execute(
            text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
            {"id": sid, "user_id": 1},
        )
    owned_row = _uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO chat_search_results "
            "(id, session_id, store_id, product_title, price_local, "
            "currency, url, position) "
            "VALUES (:id, :sid, :store_id, :title, :price, :currency, :url, "
            ":position)"
        ),
        {
            "id": str(owned_row),
            "sid": owner,
            "store_id": "amazon_eg",
            "title": "Someone else's monitor",
            "price": 100.0,
            "currency": "EGP",
            "url": "https://example.com/private",
            "position": 0,
        },
    )
    db_session.commit()

    response = client.post(
        "/chatbot/add-to-feed",
        json={"session_id": intruder, "result_id": str(owned_row)},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert posted == []
    assert "private" not in response.json()["message"]


def test_add_to_feed_rejects_a_session_owned_by_another_user(
    client, override_db, override_auth, db_session, auth_headers, monkeypatch
):
    """A session id is not a capability.

    Result rows are already scoped by session_id, but the session itself is
    named by the client, so ownership has to be checked: guessing another
    user's session uuid must not track their products, must not reveal the
    session exists, and must not write into it.
    """
    import uuid as _uuid

    posted = _capture_add_posts(monkeypatch)

    victim_session = str(_uuid.uuid4())
    row_id = _uuid.uuid4()
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": victim_session, "user_id": 1},
    )
    db_session.execute(
        text(
            "INSERT INTO chat_search_results "
            "(id, session_id, store_id, product_title, price_local, "
            "currency, url, position) "
            "VALUES (:id, :sid, :store_id, :title, :price, :currency, :url, "
            ":position)"
        ),
        {
            "id": str(row_id),
            "sid": victim_session,
            "store_id": "amazon_eg",
            "title": "Private monitor",
            "price": 100.0,
            "currency": "EGP",
            "url": "https://example.com/private",
            "position": 0,
        },
    )
    db_session.commit()

    # A different user asks, with the same (valid) token headers.
    app.dependency_overrides[get_authenticated_user_id] = lambda: 2

    response = client.post(
        "/chatbot/add-to-feed",
        json={"session_id": victim_session, "result_id": str(row_id)},
        headers=auth_headers,
    )

    assert response.status_code == 200
    # No tracker was created, the product is not named, and the victim's
    # session stayed untouched.
    assert posted == []
    body = response.json()["message"]
    assert "Private" not in body and "private" not in body
    messages = db_session.execute(
        text("SELECT COUNT(*) FROM chat_messages WHERE session_id = :sid"),
        {"sid": victim_session},
    ).scalar()
    assert messages == 0


def test_add_command_resolves_position_against_saved_results(
    client, override_db, override_auth, db_session, auth_headers, monkeypatch
):
    """An Arabic "add number 2" command adds the second saved result.

    The reference is resolved from the chat_search_results rows, so it survives
    a container restart that clears the in-process cache.
    """
    from services.chatbot import main as main_module

    posted = _capture_add_posts(monkeypatch)

    class FakeSearchService:
        async def search_with_intent(self, message):
            return {
                "query": "laptop",
                "search_query": "laptop",
                "display_query": "laptop",
                "min_price": None,
                "max_price": None,
                "language": "en",
                "store_status": [],
                "results": [
                    {
                        "store_id": "amazon_eg",
                        "store_name": "Amazon.eg",
                        "title": "Lenovo LOQ Laptop",
                        "url": "https://example.com/first",
                        "price": 64999.0,
                        "currency": "EGP",
                    },
                    {
                        "store_id": "noon_eg",
                        "store_name": "Noon.eg",
                        "title": "Acer Nitro V Laptop",
                        "url": "https://example.com/second",
                        "price": 55799.0,
                        "currency": "EGP",
                    },
                ],
            }

    monkeypatch.setattr(main_module, "search_service", FakeSearchService())

    search_response = client.post(
        "/chatbot/message",
        json={"message": "laptop"},
        headers=auth_headers,
    )
    assert search_response.status_code == 200
    assert len(search_response.json()["search_results"]) == 2
    # The server owns session identity; the follow-up uses the id it returned.
    session_id = search_response.json()["session_id"]

    # "أضف رقم 2" = "add it, number 2" in Egyptian Arabic.
    add_response = client.post(
        "/chatbot/message",
        json={"message": "أضف رقم 2", "session_id": session_id},
        headers=auth_headers,
    )

    assert add_response.status_code == 200

    assert posted == ["https://example.com/second"]
    # The session is Arabic, so the confirmation comes back in Arabic.
    assert add_response.json()["message"].startswith("تمام!")


def test_a_backfilled_session_resolves_the_nth_ordinal_from_the_db(
    client, override_db, override_auth, db_session, auth_headers, monkeypatch
):
    """Positions are stored 0-based; the Arabic ordinal counts from 1.

    Migration 0011 re-ranks rows written before the column existed as 0..n-1
    inside their session, so "add, number 3" must land on the row whose position
    is 2 — and it must resolve from the database, because this process never
    saw the search that produced them.
    """
    import uuid as _uuid

    from services.chatbot import main as main_module

    posted = _capture_add_posts(monkeypatch)

    session_id = _uuid.uuid4()
    db_session.execute(
        text("INSERT INTO chat_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": str(session_id), "user_id": 1},
    )
    for position, url in enumerate(
        (
            "https://example.com/first",
            "https://example.com/second",
            "https://example.com/third",
        )
    ):
        db_session.execute(
            text(
                "INSERT INTO chat_search_results "
                "(id, session_id, store_id, product_title, price_local, "
                "currency, url, position) "
                "VALUES (:id, :sid, :store_id, :title, :price, :currency, :url, "
                ":position)"
            ),
            {
                "id": str(_uuid.uuid4()),
                "sid": str(session_id),
                "store_id": "amazon_eg",
                "title": f"Product {position}",
                "price": 100.0 + position,
                "currency": "EGP",
                "url": url,
                "position": position,
            },
        )
    db_session.commit()

    # The in-process view of this session must be cold: the answer comes from
    # the ranked rows, exactly as it does after a container restart.
    main_module._active_results_cache.clear()

    response = client.post(
        "/chatbot/message",
        # "\u0623\u0636\u0641 \u0631\u0642\u0645 3" — "add, number 3" in
        # Egyptian Arabic, written with escapes so the glyphs cannot mojibake.
        json={
            "message": "\u0623\u0636\u0641 \u0631\u0642\u0645 3",
            "session_id": str(session_id),
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert posted == ["https://example.com/third"]


def test_store_status_endpoint(client, override_db, override_auth):
    """The client can ask which stores answered and which did not."""
    response = client.get("/chatbot/stores")

    assert response.status_code == 200
    data = response.json()
    assert data["stores"] == []

    # Warm the health tracker, then the endpoint reports it.
    from services.chatbot import main as main_module

    main_module.search_service.store_health.record(
        "amazon_eg", "blocked", detail="HTTP 403"
    )

    response = client.get("/chatbot/stores")
    entry = response.json()["stores"][0]

    assert entry["store_id"] == "amazon_eg"
    assert entry["state"] == "blocked"
    assert entry["detail"] == "HTTP 403"
    main_module.search_service.store_health.reset()


def test_message_over_the_length_bound_is_rejected(
    client, override_db, override_auth, auth_headers
):
    """The 500-char bound is enforced by the model, before any work happens."""
    response = client.post(
        "/chatbot/message",
        json={"message": "x" * 501},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_session_timestamps_are_reported(
    client, override_db, override_auth, db_session
):
    """A session reports real created/updated times, not nulls."""
    from services.chatbot.main import _ensure_session

    session_id = str(_ensure_session(db_session, None, 1))

    response = client.get(f"/chatbot/sessions/{session_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_rate_limit_key_prefers_the_authenticated_user(monkeypatch):
    """Rate limits are per user, so one user's searches cannot throttle another."""
    from unittest.mock import MagicMock

    from services.chatbot.main import rate_limit_key

    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    request = MagicMock(
        headers={"Authorization": f"Bearer {_make_token('+201234567890')}"}
    )

    assert rate_limit_key(request) == "user:+201234567890"


def test_rate_limit_key_falls_back_to_the_client_ip(monkeypatch):
    """A missing or forged token must not disable the limit."""
    from unittest.mock import MagicMock

    from services.chatbot.main import rate_limit_key

    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    request = MagicMock(headers={"Authorization": "Bearer not-a-jwt"})
    request.client.host = "10.0.0.1"
    request.client.port = 1234

    assert rate_limit_key(request) == "10.0.0.1"


# ---------------------------------------------------------------------------
# Cleanup (session-scoped to avoid file locking)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    """Remove the test database file after all tests in the session."""
    yield
    try:
        os.remove(TEST_DB_PATH)
    except FileNotFoundError:
        pass
    except PermissionError:
        # File may be locked by a concurrent process; ignore.
        pass
