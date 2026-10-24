"""Chatbot service — FastAPI entry point.

Endpoints:
* POST /chatbot/message     — Send a message; returns bot response + search results
* GET  /chatbot/sessions    — List the user's chat sessions
* GET  /chatbot/sessions/{id} — Get a session with its messages
* GET  /health              — Health check

The chatbot service is isolated from other services: it uses Crawl4AI as a
library for on-demand product search and calls the API service via REST
(httpx) to create tracked items when a user taps "Add to Feed".

All endpoints require a valid JWT Bearer token (issued by the API service).
The token's `sub` claim is the user's phone number; the chatbot looks up the
user in the shared operational PostgreSQL database to resolve the internal
user_id. This prevents any client from impersonating another user or
accessing another user's sessions.

Database design note: the chatbot shares the operational PostgreSQL database
with the API service. This is intentional — the `users` table is owned by the
API service, and the chatbot only reads from it to resolve user_id from the
JWT `sub` claim. The chatbot owns its own tables (`chat_sessions`,
`chat_messages`, `chat_search_results`) and never writes to `users` or any
other service's tables. This avoids the need for a separate user database
or a cross-service REST call for every authentication check.
"""

import logging
import os
from typing import List, Optional
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from models import (
    AddToFeedRequest,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SearchResult,
)
from arabic_nlp import detect_language, parse_add_command
from i18n import format_message
from search_service import ChatbotSearchService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
)
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000")

# JWT configuration — must match the API service exactly.
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

if not SECRET_KEY:
    logger.warning("SECRET_KEY is not set; JWT validation will fail for all requests.")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Rate limit exception handler
# ---------------------------------------------------------------------------


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        content={"detail": "Rate limit exceeded. Please try again later."},
        status_code=429,
    )


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


security = HTTPBearer()


def verify_jwt_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Decode and validate the JWT Bearer token.

    Returns the JWT payload dict. Raises HTTPException(401) on any failure.
    """
    if not SECRET_KEY:
        raise HTTPException(
            status_code=503, detail="JWT secret not configured on server"
        )
    try:
        payload = jwt.decode(
            credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM]
        )
    except JWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return payload


def get_authenticated_user_id(
    payload: dict = Depends(verify_jwt_token),
    db: Session = Depends(get_db),
) -> int:
    """Resolve the authenticated user's internal ID from the JWT.

    The JWT `sub` claim is the user's phone number. We look up the user in
    the shared operational PostgreSQL database to obtain the internal
    user_id. This ensures the client cannot supply an arbitrary user_id.
    """
    phone = payload.get("sub")
    if not phone:
        raise HTTPException(
            status_code=401, detail="Token does not contain a user subject"
        )

    row = db.execute(
        text("SELECT id FROM users WHERE phone = :phone"),
        {"phone": phone},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="User not found")

    return int(row.id)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="El72 Chatbot")

# Add rate limiting middleware and exception handler
app.add_middleware(SlowAPIMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Singleton search service instance
search_service = ChatbotSearchService()
_active_search_results: dict[UUID, list[dict]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check."""
    return HealthResponse()


@app.post("/chatbot/message", response_model=ChatResponse)
@limiter.limit("10/minute")
async def send_message(
    request: Request,
    chat_request: ChatRequest,
    user_id: int = Depends(get_authenticated_user_id),
    db: Session = Depends(get_db),
):
    """Send a message to the chatbot.

    Requires a valid JWT Bearer token. The authenticated user_id is used
    for all session operations, preventing impersonation.

    Input bounds: message must be 1–500 characters to prevent abuse and
    keep search queries reasonable.
    """
    if len(chat_request.message) > 500:
        raise HTTPException(
            status_code=400,
            detail="Message must be 500 characters or fewer.",
        )

    # Ensure the session exists (server-generated UUID if not provided)
    session_id = _ensure_session(db, chat_request.session_id, user_id)

    # Save user message
    _save_message(db, session_id, "user", chat_request.message)

    # Arabic add commands act on the latest result set in this session.
    language = detect_language(chat_request.message)
    add_index = parse_add_command(chat_request.message) if language == "ar" else None
    if add_index is not None:
        cached_results = _active_search_results.get(session_id, [])
        if 1 <= add_index <= len(cached_results):
            return await _handle_add_to_feed(
                AddToFeedRequest(
                    session_id=session_id,
                    user_id=user_id,
                    result_id=cached_results[add_index - 1]["url"],
                ),
                db,
                language=language,
            )
        message = format_message("no_search_results", language)
        _save_message(db, session_id, "bot", message)
        return ChatResponse(
            message=message,
            session_id=session_id,
            search_results=[],
            language=language,
        )

    # Parse intent and search
    intent_result = await search_service.search_with_intent(chat_request.message)
    query = intent_result["display_query"]
    max_price = intent_result["max_price"]
    results = intent_result["results"]
    language = intent_result["language"]
    _active_search_results[session_id] = results

    # Save search results to chat_search_results (denormalized for quick reads)
    for result in results:
        _save_search_result(db, session_id, result)

    # Build bot response
    price_filter = (
        format_message("price_filter", language, max_price=max_price)
        if max_price is not None
        else ""
    )
    if not results:
        bot_message = format_message(
            "empty_query" if not query else "no_results",
            language,
            query=query,
            price_filter=price_filter,
        )
    else:
        count = len(results)
        plural = (
            "s"
            if language == "en" and count != 1
            else "ات"
            if language == "ar" and count > 2
            else ""
        )
        bot_message = format_message(
            "found_results",
            language,
            count=count,
            plural=plural,
            query=query,
            price_filter=price_filter,
        )

    # Save bot message
    _save_message(db, session_id, "bot", bot_message)

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
        session_id=session_id,
        search_results=search_results,
        language=language,
    )


@app.post("/chatbot/add-to-feed", response_model=ChatResponse)
@limiter.limit("10/minute")
async def add_to_feed(
    request: Request,
    add_to_feed_request: AddToFeedRequest,
    user_id: int = Depends(get_authenticated_user_id),
    db: Session = Depends(get_db),
):
    """Add a search result to the user's tracking feed.

    Accepts a session_id and an optional product_url. If product_url is
    provided, looks up that specific search result. Otherwise falls back
    to the most recent search result for the session.
    """
    return await _handle_add_to_feed(
        AddToFeedRequest(
            session_id=add_to_feed_request.session_id,
            user_id=user_id,
            result_id=add_to_feed_request.result_id,
            target_price=add_to_feed_request.target_price,
        ),
        db,
        language="en",
    )


@app.get("/chatbot/sessions", response_model=List[dict])
@limiter.limit("30/minute")
async def list_sessions(
    request: Request,
    user_id: int = Depends(get_authenticated_user_id),
    db: Session = Depends(get_db),
):
    """List all chat sessions for the authenticated user."""
    rows = db.execute(
        text(
            "SELECT id, user_id, created_at, updated_at FROM chat_sessions "
            "WHERE user_id = :user_id ORDER BY updated_at DESC"
        ),
        {"user_id": user_id},
    ).fetchall()

    return [
        {
            "id": str(row.id),
            "user_id": row.user_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@app.get("/chatbot/sessions/{session_id}", response_model=dict)
@limiter.limit("30/minute")
async def get_session(
    request: Request,
    session_id: UUID,
    user_id: int = Depends(get_authenticated_user_id),
    db: Session = Depends(get_db),
):
    """Get a chat session with all its messages.

    Ownership is enforced: only the session's owner can read it.
    """
    # Verify ownership
    row = db.execute(
        text(
            "SELECT id, user_id FROM chat_sessions "
            "WHERE id = :session_id AND user_id = :user_id"
        ),
        {"session_id": str(session_id), "user_id": user_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Chat session not found")

    messages = db.execute(
        text(
            "SELECT id, role, content, created_at FROM chat_messages "
            "WHERE session_id = :session_id ORDER BY created_at"
        ),
        {"session_id": str(session_id)},
    ).fetchall()

    return {
        "id": str(row.id),
        "user_id": row.user_id,
        "created_at": None,
        "updated_at": None,
        "messages": [
            {
                "id": str(m.id),
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


def _ensure_session(db: Session, session_id: Optional[UUID], user_id: int) -> UUID:
    """Ensure a chat session row exists.

    If session_id is provided and a row with that id already exists for this
    user, reuse it. Otherwise generate a new server-side UUID.
    """
    if session_id is not None:
        # Verify the session belongs to this user before reusing
        existing = db.execute(
            text(
                "SELECT id FROM chat_sessions "
                "WHERE id = :session_id AND user_id = :user_id"
            ),
            {"session_id": str(session_id), "user_id": user_id},
        ).fetchone()
        if existing:
            return existing.id

    # Generate a new server-side UUID
    import uuid as _uuid

    new_id = _uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO chat_sessions (id, user_id) " "VALUES (:session_id, :user_id)"
        ),
        {"session_id": str(new_id), "user_id": user_id},
    )
    db.commit()
    return new_id


def _save_message(db: Session, session_id: UUID, role: str, content: str):
    """Save a chat message to the database."""
    import uuid as _uuid

    message_id = _uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO chat_messages (id, session_id, role, content) "
            "VALUES (:message_id, :session_id, :role, :content)"
        ),
        {
            "message_id": str(message_id),
            "session_id": str(session_id),
            "role": role,
            "content": content,
        },
    )
    db.commit()


def _save_search_result(db: Session, session_id: UUID, result: dict):
    """Save a search result to the database (denormalized for quick reads)."""
    import uuid as _uuid

    result_id = _uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO chat_search_results "
            "(id, session_id, store_id, product_title, "
            "price_local, currency, url, image_url) "
            "VALUES (:result_id, :session_id, :store_id, "
            ":title, :price, :currency, :url, :image_url)"
        ),
        {
            "result_id": str(result_id),
            "session_id": str(session_id),
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
    request: AddToFeedRequest,
    db: Session,
    language: str = "en",
) -> ChatResponse:
    """Handle an 'add to feed' action.

    If [request.result_id] is a URL, looks up that specific search result.
    Otherwise falls back to the most recent search result for the session.
    Creates a tracked item via the API service.
    """
    # Find the search result for this session.
    if request.result_id:
        row = db.execute(
            text(
                "SELECT store_id, product_title, price_local, currency, url, image_url "
                "FROM chat_search_results "
                "WHERE session_id = :session_id AND url = :url "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"session_id": str(request.session_id), "url": request.result_id},
        ).fetchone()
    else:
        row = db.execute(
            text(
                "SELECT store_id, product_title, price_local, currency, url, image_url "
                "FROM chat_search_results "
                "WHERE session_id = :session_id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"session_id": str(request.session_id)},
        ).fetchone()

    if not row:
        message = format_message("no_search_results", language)
        _save_message(db, request.session_id, "bot", message)
        return ChatResponse(
            message=message,
            session_id=request.session_id,
            search_results=[],
            language=language,
        )

    url = row.url
    title = row.product_title
    price = float(row.price_local) if row.price_local else None
    target_price = request.target_price or price

    # Call the API service to create a tracked item
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {"url": url}
            if target_price and target_price > 0:
                payload["target_price"] = target_price

            response = await client.post(
                f"{API_BASE_URL}/tracked-items/from-url",
                json=payload,
            )

            if response.status_code == 402:
                detail = response.json().get("detail", "Insufficient credits")
                message = format_message(
                    "insufficient_credits", language, detail=detail
                )
                _save_message(
                    db, request.session_id, "bot", message
                )
                return ChatResponse(
                    message=message,
                    session_id=request.session_id,
                    search_results=[],
                    language=language,
                )

            response.raise_for_status()
            response.json()

        message = format_message("added_to_feed", language, title=title)
        _save_message(db, request.session_id, "bot", message)

        return ChatResponse(
            message=message,
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
            language=language,
        )

    except httpx.HTTPError as e:
        logger.error(f"API call failed: {e}")
        message = format_message("add_failed", language)
        _save_message(db, request.session_id, "bot", message)
        return ChatResponse(
            message=message,
            session_id=request.session_id,
            search_results=[],
            language=language,
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
