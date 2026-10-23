"""Chatbot service — FastAPI entry point.

Endpoints:
* POST /chatbot/message     — Send a message; returns bot response + search results
* GET  /chatbot/sessions    — List the user's chat sessions
* GET  /chatbot/sessions/{id} — Get a session with its messages
* GET  /health              — Health check

The chatbot service is isolated from other services: it uses Crawl4AI as a
library for on-demand product search and calls the API service via REST
(httpx) to create tracked items when a user taps "Add to Feed".
"""

import logging
import os
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from services.chatbot.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SearchResult,
)
from services.chatbot.search_service import ChatbotSearchService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
)
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_db():
    """Yield a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="El72 Chatbot")

# Singleton search service instance
search_service = ChatbotSearchService()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check."""
    return HealthResponse()


@app.post("/chatbot/message", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
):
    """Send a message to the chatbot.

    Parses intent, searches for products across stores, and returns results.
    If the message is an "add_to_feed" action, creates a tracked item via the
    API service.
    """
    # Ensure the session exists (idempotent)
    _ensure_session(db, request.session_id, request.user_id)

    # Save user message
    _save_message(db, request.session_id, "user", request.message)

    # Check for add-to-feed action
    if request.message.strip().lower() in ("add to feed", "add this", "track this"):
        return await _handle_add_to_feed(request, db)

    # Parse intent and search
    intent_result = await search_service.search_with_intent(request.message)
    query = intent_result["query"]
    max_price = intent_result["max_price"]
    results = intent_result["results"]

    # Save search results to chat_search_results (denormalized for quick reads)
    for result in results:
        _save_search_result(db, request.session_id, result)

    # Build bot response
    if not results:
        bot_message = (
            f"I couldn't find any products matching '{query}' "
            + (f" under {max_price} EGP" if max_price else "")
            + ". Try a different search term."
        )
    else:
        count = len(results)
        price_filter = f" under {max_price} EGP" if max_price else ""
        bot_message = (
            f"I found {count} product{'s' if count > 1 else ''} "
            f"matching '{query}'{price_filter}:"
        )

    # Save bot message
    _save_message(db, request.session_id, "bot", bot_message)

    # Convert results to SearchResult models
    search_results = [
        SearchResult(
            store_id=r["store_id"],
            store_name=r["store_name"],
            title=r["title"],
            price=r["price"],
            currency=r["currency"],
            url=r["url"],
            image_url=r.get("image_url", ""),
            in_stock=r.get("in_stock", True),
        )
        for r in results
    ]

    return ChatResponse(
        message=bot_message,
        session_id=request.session_id,
        search_results=search_results,
    )


@app.get("/chatbot/sessions", response_model=List[dict])
async def list_sessions(
    user_id: int,
    db: Session = Depends(get_db),
):
    """List all chat sessions for a user."""
    rows = db.execute(
        text(
            "SELECT id, user_id, created_at, updated_at FROM chat_sessions "
            "WHERE user_id = :user_id ORDER BY updated_at DESC"
        ),
        {"user_id": user_id},
    ).fetchall()

    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@app.get("/chatbot/sessions/{session_id}", response_model=dict)
async def get_session(
    session_id: int,
    db: Session = Depends(get_db),
):
    """Get a chat session with all its messages."""
    session = db.execute(
        text(
            "SELECT id, user_id, created_at, updated_at FROM chat_sessions "
            "WHERE id = :session_id"
        ),
        {"session_id": session_id},
    ).fetchone()

    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    messages = db.execute(
        text(
            "SELECT id, role, content, created_at FROM chat_messages "
            "WHERE session_id = :session_id ORDER BY created_at"
        ),
        {"session_id": session_id},
    ).fetchall()

    return {
        "id": session.id,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat()
        if session.updated_at
        else None,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _ensure_session(db: Session, session_id: int, user_id: int):
    """Ensure a chat session row exists (idempotent)."""
    db.execute(
        text(
            "INSERT INTO chat_sessions (id, user_id) "
            "VALUES (:session_id, :user_id) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"session_id": session_id, "user_id": user_id},
    )
    db.commit()


def _save_message(db: Session, session_id: int, role: str, content: str):
    """Save a chat message to the database."""
    db.execute(
        text(
            "INSERT INTO chat_messages (session_id, role, content) "
            "VALUES (:session_id, :role, :content)"
        ),
        {
            "session_id": session_id,
            "role": role,
            "content": content,
        },
    )
    db.commit()


def _save_search_result(db: Session, session_id: int, result: dict):
    """Save a search result to the database (denormalized for quick reads)."""
    db.execute(
        text(
            "INSERT INTO chat_search_results "
            "(session_id, store_id, product_title, price_local, currency, url, image_url) "
            "VALUES (:session_id, :store_id, :title, :price, :currency, :url, :image_url)"
        ),
        {
            "session_id": session_id,
            "store_id": result["store_id"],
            "title": result["title"],
            "price": result["price"],
            "currency": result["currency"],
            "url": result["url"],
            "image_url": result.get("image_url", ""),
        },
    )
    db.commit()


async def _handle_add_to_feed(
    request: ChatRequest,
    db: Session,
) -> ChatResponse:
    """Handle an 'add to feed' action.

    Looks up the most recent search result for the session and creates a
    tracked item via the API service.
    """
    # Find the most recent search result for this session
    row = db.execute(
        text(
            "SELECT store_id, product_title, price_local, currency, url, image_url "
            "FROM chat_search_results "
            "WHERE session_id = :session_id "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"session_id": request.session_id},
    ).fetchone()

    if not row:
        _save_message(
            db, request.session_id, "bot", "No search results found to add."
        )
        return ChatResponse(
            message="No search results found to add to your feed.",
            session_id=request.session_id,
            search_results=[],
        )

    url = row.url
    title = row.product_title
    price = float(row.price_local) if row.price_local else None

    # Call the API service to create a tracked item
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {"url": url}
            if price and price > 0:
                payload["target_price"] = price

            response = await client.post(
                f"{API_BASE_URL}/tracked-items/from-url",
                json=payload,
            )

            if response.status_code == 402:
                _save_message(
                    db,
                    request.session_id,
                    "bot",
                    "You don't have enough credits to create a tracker. "
                    "Consider upgrading your plan.",
                )
                return ChatResponse(
                    message="Insufficient credits to add this tracker. "
                    "Upgrade your plan to continue.",
                    session_id=request.session_id,
                    search_results=[],
                )

            response.raise_for_status()
            api_result = response.json()

        _save_message(
            db,
            request.session_id,
            "bot",
            f"I've added '{title}' to your tracking feed. "
            f"I'll monitor the price and notify you when it changes.",
        )

        return ChatResponse(
            message=api_result.get(
                "message", "Added to your tracking feed successfully."
            ),
            session_id=request.session_id,
            search_results=[
                SearchResult(
                    store_id=row.store_id,
                    store_name="",
                    title=title,
                    price=price or 0.0,
                    currency=row.currency or "EGP",
                    url=url,
                    image_url=row.image_url or "",
                    in_stock=True,
                )
            ],
        )

    except httpx.HTTPError as e:
        logger.error(f"API call failed: {e}")
        _save_message(
            db,
            request.session_id,
            "bot",
            "Sorry, I couldn't add this to your feed at the moment. "
            "Please try again later.",
        )
        return ChatResponse(
            message="Failed to add to feed. Please try again later.",
            session_id=request.session_id,
            search_results=[],
        )


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _startup():
    """Initialize the search service on startup."""
    logger.info("Chatbot service starting up...")


@app.on_event("shutdown")
async def _shutdown():
    """Clean up resources on shutdown."""
    await search_service.close()
    logger.info("Chatbot service shut down.")
