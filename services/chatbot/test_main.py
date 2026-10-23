"""Unit tests for the chatbot service."""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.chatbot.main import app, get_db
from services.chatbot.search_service import (
    ChatbotSearchService,
    parse_intent,
    STORES,
)

# Use file-based SQLite for test isolation (in-memory is per-connection)
TEST_DB_PATH = "test_chatbot.db"
TEST_ENGINE = create_engine(f"sqlite:///{TEST_DB_PATH}")
TEST_SESSION_LOCAL = sessionmaker(
    autocommit=False, autoflush=False, bind=TEST_ENGINE
)


@pytest.fixture(scope="module")
def client():
    """Create a test client with the FastAPI app."""
    from fastapi.testclient import TestClient

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

        # Create chat tables
        db.execute(
            text(
                "CREATE TABLE chat_sessions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE chat_messages ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "session_id INTEGER NOT NULL, "
                "role VARCHAR(10) NOT NULL, "
                "content TEXT NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE chat_search_results ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "session_id INTEGER NOT NULL, "
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


def test_health_endpoint(client):
    """Test the health endpoint returns 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "chatbot"


def test_list_sessions_empty(client, override_db):
    """Test listing sessions when there are none."""
    response = client.get("/chatbot/sessions?user_id=1")
    assert response.status_code == 200
    assert response.json() == []


def test_get_session_not_found(client, override_db):
    """Test getting a non-existent session returns 404."""
    response = client.get("/chatbot/sessions/999")
    assert response.status_code == 404


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

