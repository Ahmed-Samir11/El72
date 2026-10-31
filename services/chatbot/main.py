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
import uuid
from typing import Any, List, Optional
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

try:
    from services.chatbot.arabic_nlp import detect_language, parse_add_command
    from services.chatbot.cache import TTLLRUCache
    from services.chatbot.i18n import format_message
    from services.chatbot.models import (
        AddToFeedRequest,
        ChatRequest,
        ChatResponse,
        HealthResponse,
        SearchResult,
    )
    from services.chatbot.search_service import ChatbotSearchService
except ImportError:
    from arabic_nlp import detect_language, parse_add_command
    from cache import TTLLRUCache
    from i18n import format_message
    from models import (
        AddToFeedRequest,
        ChatRequest,
        ChatResponse,
        HealthResponse,
        SearchResult,
    )
    from search_service import ChatbotSearchService

# The JWT contract (HS256, SECRET_KEY, sub = phone number) is shared with the
# API service through services/common; decoding it here keeps the two from
# drifting apart on expiry handling or algorithm choice.
try:
    from services.common.auth import (
        TokenDecodeError,
        bearer_token,
        decode_access_token,
        token_subject,
    )
except ImportError:  # container layout: services/common -> /app/common
    from common.auth import (  # noqa: E402
        TokenDecodeError,
        bearer_token,
        decode_access_token,
        token_subject,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
)
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000")


# JWT configuration — decoding lives in services/common/auth.py, which pins
# the algorithm, so this service cannot pick a different one by accident. The
# secret itself is read when a request is validated, not at import: import order
# (or a container that gains the variable later) must not decide whether tokens
# can be verified.
def configured_secret() -> Optional[str]:
    """The configured ``SECRET_KEY``, or ``None`` when it is unset."""
    return os.getenv("SECRET_KEY")


if not configured_secret():
    logger.warning("SECRET_KEY is not set; JWT validation will fail for all requests.")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def rate_limit_key(request: Request) -> str:
    """Rate-limit per authenticated user, falling back to the client address.

    Keying on the IP means one shared NAT pool or proxy rotation shares a
    bucket — and lets an attacker dodge the limit by changing address. The
    token's ``sub`` is the real principal, so a user's budget follows them.
    Unauthenticated or malformed tokens fall back to the address.
    """
    token = bearer_token(request.headers.get("Authorization"))
    if token:
        try:
            payload = decode_access_token(token, configured_secret())
        except TokenDecodeError:
            payload = None
        subject = token_subject(payload) if payload else None
        if subject:
            return f"user:{subject}"
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)


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
    secret = configured_secret()
    if not secret:
        raise HTTPException(
            status_code=503, detail="JWT secret not configured on server"
        )
    try:
        return decode_access_token(credentials.credentials, secret)
    except TokenDecodeError:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_authenticated_user_id(
    payload: dict = Depends(verify_jwt_token),
    db: Session = Depends(get_db),
) -> int:
    """Resolve the authenticated user's internal ID from the JWT.

    The JWT `sub` claim is the user's phone number. We look up the user in
    the shared operational PostgreSQL database to obtain the internal
    user_id. This ensures the client cannot supply an arbitrary user_id.
    """
    phone = token_subject(payload)
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

# Singleton search service instance. The session factory lets it mirror warm
# search results into chat_query_cache, so restarting the container does not
# throw away what every store a user just asked about.
search_service = ChatbotSearchService(db_session_factory=SessionLocal)

# Latest search results per session, which "أضf رقم N" acts on. Bounded on
# purpose: an unbounded dict keyed by session id grew for the lifetime of the
# process. Expired entries fall back to chat_search_results (see [_active_results]).
ACTIVE_RESULTS_TTL_SECONDS = 30 * 60
ACTIVE_RESULTS_MAX_SESSIONS = 512
_active_results_cache = TTLLRUCache(
    ACTIVE_RESULTS_MAX_SESSIONS, ACTIVE_RESULTS_TTL_SECONDS
)


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

    Input bounds: the message is 1–500 characters, enforced by [ChatRequest]
    so an oversized body is rejected with 422 before any work happens.
    """
    # Ensure the session exists (server-generated UUID if not provided)
    session_id = _ensure_session(db, chat_request.session_id, user_id)

    # Save user message
    _save_message(db, session_id, "user", chat_request.message)

    # Arabic add commands act on the latest result set in this session.
    language = detect_language(chat_request.message)
    add_index = parse_add_command(chat_request.message) if language == "ar" else None
    if add_index is not None:
        cached_results = _active_results(db, session_id)
        if 1 <= add_index <= len(cached_results):
            chosen = cached_results[add_index - 1]
            return await _handle_add_to_feed(
                AddToFeedRequest(
                    session_id=session_id,
                    user_id=user_id,
                    # Prefer the saved row id: it is unique per result, while a
                    # URL can repeat across searches in the same session.
                    result_id=chosen.get("result_id") or chosen["url"],
                ),
                db,
                auth_header=request.headers.get("Authorization", ""),
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
    min_price = intent_result.get("min_price")
    results = intent_result["results"]
    language = intent_result["language"]
    store_status = intent_result.get("store_status", [])

    # Save search results to chat_search_results (denormalized for quick reads)
    # and remember this set as the session's active one. The row id travels with
    # each result so a later "أضf رقم N" resolves to the product the user is
    # looking at, even after the in-process cache expires.
    search_id = uuid.uuid4()
    active_results: List[dict] = []
    for position, result in enumerate(results):
        result_id = _save_search_result(db, session_id, search_id, result, position)
        active_results.append(
            {**result, "result_id": str(result_id), "search_id": str(search_id)}
        )
    _active_results_cache.set(str(session_id), active_results)

    # Build bot response
    if min_price is not None and max_price is not None:
        price_filter = format_message(
            "price_range", language, min_price=min_price, max_price=max_price
        )
    elif min_price is not None:
        price_filter = format_message("price_min", language, min_price=min_price)
    elif max_price is not None:
        price_filter = format_message("price_filter", language, max_price=max_price)
    else:
        price_filter = ""
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
            else "ات" if language == "ar" and count > 2 else ""
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
            result_id=r["result_id"],
        )
        for r in active_results
    ]

    return ChatResponse(
        message=bot_message,
        session_id=session_id,
        search_results=search_results,
        language=language,
        store_status=store_status,
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

    Accepts a session_id and an optional result reference. When it is a saved
    result id the exact row is used; a URL is still accepted as the deprecated
    alias. Without a reference the most recent search result for the session
    is added.
    """
    # The result reference is resolved inside a session the client names, so
    # the session itself has to be checked against the authenticated user first:
    # a guessed session UUID must not read (or track) another user's searches.
    if not _session_is_owned(db, add_to_feed_request.session_id, user_id):
        # Answered exactly as if the session had nothing to add. A distinct
        # "not yours" reply would itself confirm the session exists.
        message = format_message("no_search_results", "en")
        return ChatResponse(
            message=message,
            session_id=add_to_feed_request.session_id,
            search_results=[],
            language="en",
        )

    return await _handle_add_to_feed(
        AddToFeedRequest(
            session_id=add_to_feed_request.session_id,
            user_id=user_id,
            result_id=add_to_feed_request.result_id,
            target_price=add_to_feed_request.target_price,
        ),
        db,
        auth_header=request.headers.get("Authorization", ""),
        # The request carries no text of its own, so phrase the reply in the
        # language this session has been using instead of defaulting to English.
        language=_session_language(db, add_to_feed_request.session_id),
    )


@app.get("/chatbot/stores", response_model=dict)
@limiter.limit("30/minute")
async def store_status(
    request: Request,
    user_id: int = Depends(get_authenticated_user_id),
):
    """Report which stores the chatbot can currently reach.

    Lets the UI (and an operator) see that an answer was partial: a store
    reported as "blocked" or "cooling" is not silently missing from the list.
    """
    return {"stores": search_service.store_health.snapshot()}


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
            "created_at": _timestamp(row.created_at),
            "updated_at": _timestamp(row.updated_at),
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
            "SELECT id, user_id, created_at, updated_at FROM chat_sessions "
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
        "created_at": _timestamp(row.created_at),
        "updated_at": _timestamp(row.updated_at),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": _timestamp(m.created_at),
            }
            for m in messages
        ],
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _timestamp(value: Any) -> Optional[str]:
    """Render a DB timestamp column as ISO text.

    Postgres returns datetime objects; the SQLite driver used in tests returns
    the stored string. Either way the endpoint must answer, not crash.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


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
            # Activity must be visible: without this bump, updated_at only ever
            # reflected session creation and GET /chatbot/sessions could not
            # tell the user which session they used last.
            db.execute(
                text(
                    "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :session_id"
                ),
                {"session_id": str(session_id)},
            )
            db.commit()
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


def _save_search_result(
    db: Session,
    session_id: UUID,
    search_id: UUID,
    result: dict,
    position: int = 0,
) -> UUID:
    """Save a search result to the database (denormalized for quick reads).

    Args:
        db: Database session.
        session_id: Session the search belongs to.
        search_id: Group id shared by the rows of one search, so a later read
            can tell this search apart from an older one in the same session.
        result: One result dict from [ChatbotSearchService.search].
        position: Rank inside the list the user saw, so "أضf رقم N" can be
            resolved from the database after the in-process cache expires.

    Returns:
        The UUID of the saved row, which later addresses this result.
    """
    import uuid as _uuid

    result_id = _uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO chat_search_results "
            "(id, session_id, search_id, store_id, product_title, "
            "price_local, currency, url, image_url, position) "
            "VALUES (:result_id, :session_id, :search_id, :store_id, "
            ":title, :price, :currency, :url, :image_url, :position)"
        ),
        {
            "result_id": str(result_id),
            "session_id": str(session_id),
            "search_id": str(search_id),
            "store_id": result["store_id"],
            "title": result["title"],
            "price": result["price"],
            "currency": result["currency"],
            "url": result["url"],
            "image_url": result.get("image_url", ""),
            "position": position,
        },
    )
    db.commit()
    return result_id


# Every search the service writes carries a search id, so the rows of one search
# form a group. An ordinal reference, or a reference-less "add to feed", acts on
# the *newest* search of the session: both searches restart at position 0, so
# without the group a second search would interleave with the first one.
# Rows written before migration 0011 are stamped with one deterministic legacy
# id per session, which keeps an old session readable as a single list.
def _latest_search_id(db: Session, session_id: UUID) -> Optional[str]:
    """Search id of the session's newest search, or None.

    None means nothing in this session carries a search id: the database predates
    migration 0011, or the session never completed a search. Callers then fall
    back to the pre-0011 position-window read.
    """
    row = db.execute(
        text(
            "SELECT search_id FROM chat_search_results "
            "WHERE session_id = :session_id AND search_id IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"session_id": str(session_id)},
    ).fetchone()
    if row is None or row.search_id is None:
        return None
    return str(row.search_id)


def _active_results(db: Session, session_id: UUID) -> List[dict]:
    """The session's latest search results, in the order the user saw them.

    The in-process cache is an optimization only: after a restart (or once it
    expires) the chat_search_results rows are the source of truth, so "أضf
    رقم 3" keeps pointing at the third product the user was shown.

    Returns:
        List of result dicts, oldest position first (may be empty).
    """
    cached = _active_results_cache.get(str(session_id))
    if cached is not None:
        return cached

    search_id = _latest_search_id(db, session_id)
    if search_id is not None:
        rows = db.execute(
            text(
                "SELECT id, store_id, product_title, price_local, currency, url, "
                "image_url, position "
                "FROM chat_search_results "
                "WHERE session_id = :session_id AND search_id = :search_id "
                "ORDER BY position DESC"
            ),
            {"session_id": str(session_id), "search_id": search_id},
        ).fetchall()
    else:
        rows = db.execute(
            text(
                "SELECT id, store_id, product_title, price_local, currency, url, "
                "image_url, position "
                "FROM chat_search_results "
                "WHERE session_id = :session_id "
                "ORDER BY position DESC, created_at DESC LIMIT 20"
            ),
            {"session_id": str(session_id)},
        ).fetchall()

    # Both queries come back newest-position-first; the loop below walks them
    # back to front so the list the caller sees matches the order the user saw.
    results = [
        {
            "result_id": str(row.id),
            "store_id": row.store_id,
            "store_name": row.store_id,
            "title": row.product_title,
            "price": float(row.price_local) if row.price_local is not None else 0.0,
            "currency": row.currency or "EGP",
            "url": row.url,
            "image_url": row.image_url or "",
            "in_stock": True,
        }
        for row in reversed(rows)
    ]
    if results:
        _active_results_cache.set(str(session_id), results)
    return results


def _session_is_owned(db: Session, session_id: UUID, user_id: int) -> bool:
    """Whether [session_id] is a session belonging to [user_id].

    Session ids are UUID4, but they are also the only scope a result lookup
    has, so ownership is checked rather than trusted. The chat path gets this
    for free from [_ensure_session]; add-to-feed names a session directly, so
    it must ask.
    """
    row = db.execute(
        text(
            "SELECT 1 AS owned FROM chat_sessions "
            "WHERE id = :session_id AND user_id = :user_id"
        ),
        {"session_id": str(session_id), "user_id": user_id},
    ).fetchone()
    return row is not None


def _session_language(db: Session, session_id: UUID) -> str:
    """Language of the session's most recent user message.

    Used when a request carries no text of its own (add-to-feed): an Arabic
    session must not be answered in English.
    """
    row = db.execute(
        text(
            "SELECT content FROM chat_messages "
            "WHERE session_id = :session_id AND role = 'user' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"session_id": str(session_id)},
    ).fetchone()
    if not row:
        return "en"
    return detect_language(row.content)


def _positive_int(value: Any) -> Optional[int]:
    """[value] as a positive int, else None (bools and prose are not counts)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return int(value)
    return None


def _creation_refusal_message(
    response: httpx.Response, language: str, title: str
) -> Optional[str]:
    """The user-facing reply for a tracker the API refused to create, or None.

    The API reports fair-use refusals as structured ``detail`` objects (see
    services/api/usage_limits.py) so that no client parses prose: ``409`` with
    ``code: fair_use_cap`` when the account is at its cap, and ``429`` with
    ``code: creation_rate_limit`` plus ``Retry-After`` when trackers are created
    too fast. A ``409`` without that code is the duplicate-tracker refusal.
    """
    if response.status_code not in (409, 429):
        return None
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None

    if response.status_code == 429:
        seconds = None
        if isinstance(detail, dict):
            seconds = _positive_int(detail.get("retry_after_seconds"))
        if seconds is None:
            seconds = _positive_int(response.headers.get("Retry-After"))
        if seconds is None:
            return format_message("creation_rate_limited_plain", language)
        return format_message("creation_rate_limited", language, seconds=seconds)

    if code == "fair_use_cap":
        active = _positive_int(detail.get("active_trackers"))
        cap = _positive_int(detail.get("cap"))
        if active is None or cap is None:
            return format_message("fair_use_cap_plain", language)
        return format_message("fair_use_cap", language, active=active, cap=cap)
    return format_message("already_tracking", language, title=title)


async def _handle_add_to_feed(
    request: AddToFeedRequest,
    db: Session,
    auth_header: str = "",
    language: str = "en",
) -> ChatResponse:
    """Handle an 'add to feed' action.

    [request.result_id] addresses a saved search result: a UUID string matches
    the row directly, anything else is treated as a product URL (the deprecated
    alias). With no reference, the best result of the session's latest search
    is used. Creates a tracked item via the API service, forwarding the caller's
    Authorization header so the tracker is owned by (and charged to) them.
    """
    # Find the search result for this session: by saved row id when the caller
    # has one (unique per result), else by URL, which older clients still send
    # as the deprecated "product_url" alias.
    result_ref = request.result_id
    if result_ref:
        try:
            result_uuid = str(UUID(result_ref))
        except ValueError:
            result_uuid = None

        if result_uuid:
            row = db.execute(
                text(
                    "SELECT store_id, product_title, price_local, currency, url, "
                    "image_url "
                    "FROM chat_search_results "
                    "WHERE session_id = :session_id AND id = :result_id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"session_id": str(request.session_id), "result_id": result_uuid},
            ).fetchone()
        else:
            row = db.execute(
                text(
                    "SELECT store_id, product_title, price_local, currency, url, "
                    "image_url "
                    "FROM chat_search_results "
                    "WHERE session_id = :session_id AND url = :url "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"session_id": str(request.session_id), "url": result_ref},
            ).fetchone()
    else:
        search_id = _latest_search_id(db, request.session_id)
        if search_id is not None:
            # The best row of the newest search, not its last row: position 0
            # of that group is what the user would be pointing at.
            row = db.execute(
                text(
                    "SELECT store_id, product_title, price_local, currency, "
                    "url, image_url FROM chat_search_results "
                    "WHERE session_id = :session_id AND search_id = :search_id "
                    "ORDER BY position ASC LIMIT 1"
                ),
                {"session_id": str(request.session_id), "search_id": search_id},
            ).fetchone()
        else:
            row = db.execute(
                text(
                    "SELECT store_id, product_title, price_local, currency, "
                    "url, image_url FROM chat_search_results "
                    "WHERE session_id = :session_id "
                    "ORDER BY created_at DESC, position ASC LIMIT 1"
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
                headers={"Authorization": auth_header} if auth_header else None,
            )

            refusal = _creation_refusal_message(response, language, title)
            if refusal is not None:
                _save_message(db, request.session_id, "bot", refusal)
                return ChatResponse(
                    message=refusal,
                    session_id=request.session_id,
                    search_results=[],
                    language=language,
                )

            if response.status_code == 402:
                detail = response.json().get("detail", "Insufficient credits")
                message = format_message(
                    "insufficient_credits", language, detail=detail
                )
                _save_message(db, request.session_id, "bot", message)
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
            tracker_created=True,
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
