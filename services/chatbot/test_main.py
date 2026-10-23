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
    get_db,
    verify_jwt_token,
    get_authenticated_user_id,
)
from services.chatbot.search_service import (
    ChatbotSearchService,
    parse_intent,
    STORES,
)

# ---------------------------------------------------------------------------
# Test database (SQLite — UUID stored as TEXT for test compatibility)
# ---------------------------------------------------------------------------

TEST_DB_PATH = "test_chatbot.db"
TEST_ENGINE = create_engine(f"sqlite:///{TEST_DB_PATH}")
TEST_SESSION_LOCAL = sessionmaker(
    autocommit=False, autoflush=False, bind=TEST_ENGINE
)

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


def test_add_to_feed_with_url(client, override_db, override_auth, db_session, auth_headers):
    """Test add-to-feed with a specific URL creates a tracker.

    Mocks the API service to return success.
    """
    import httpx

    # Create a session and a search result
    import uuid as _uuid

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


def test_add_to_feed_insufficient_credits(client, override_db, override_auth, db_session, auth_headers):
    """Test add-to-feed when the API returns 402 (insufficient credits)."""
    import httpx

    # Create a session and a search result
    import uuid as _uuid

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
    assert "credit" in data["message"].lower() or "insufficient" in data["message"].lower()


def test_add_to_feed_no_results(client, override_db, override_auth, db_session, auth_headers):
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
