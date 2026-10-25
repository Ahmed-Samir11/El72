"""Pydantic request/response models for the chatbot service."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchResult(BaseModel):
    """A product search result from a store.

    result_id is the id of the row saved in chat_search_results; "أضf رقم N"
    targets it, so the pick survives a restart instead of matching a URL string
    that may repeat across searches.
    """

    store_id: str
    store_name: str
    title: str
    price: float
    currency: str = "EGP"
    url: str
    image_url: Optional[str] = None
    in_stock: bool = True
    result_id: Optional[str] = None


class StoreHealthInfo(BaseModel):
    """Reachability of one store for chatbot searches.

    state is one of "ok", "empty", "blocked", "timeout", "robots_denied", "cooling"
    or "cached" — what the last search of that store actually found, which is
    how the user learns that an answer is partial rather than complete.
    """

    store_id: str
    state: str
    products: int = 0
    detail: str = ""


class ChatMessage(BaseModel):
    """A single chat message.

    id is the UUID row id from chat_messages, serialised as a string.
    """

    id: str
    session_id: UUID
    role: str  # 'user' or 'bot'
    content: str
    created_at: datetime


class ChatSession(BaseModel):
    """A chat session with its messages."""

    id: UUID
    user_id: int
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Request to send a message to the chatbot.

    Note: user_id is not supplied by the client; it is resolved server-side
    from the JWT token. If present, it is ignored.

    The message length is bounded at the model level, so an oversized body is
    rejected with 422 before it reaches the handler, the rate limiter, or the
    database.
    """

    session_id: Optional[UUID] = None
    user_id: Optional[int] = None
    message: str = Field(..., min_length=1, max_length=500)


class ChatResponse(BaseModel):
    """Response from the chatbot.

    store_status names the stores that answered, were empty, were blocked or
    were skipped, so partial results are visible as partial instead of arriving
    as an unexplained short list.
    """

    message: str
    session_id: UUID
    search_results: List[SearchResult] = Field(default_factory=list)
    language: str = "en"
    store_status: List[Dict[str, Any]] = Field(default_factory=list)


class AddToFeedRequest(BaseModel):
    """Request to add a search result to the user's feed (tracked items).

    Note: user_id is not supplied by the client; it is resolved server-side
    from the JWT token. If present, it is ignored.

    result_id is the product URL of the search result to add; clients send it
    as "product_url". It may be None when the client wants to add the latest
    search result without specifying a URL.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID
    user_id: Optional[int] = None
    result_id: Optional[str] = Field(default=None, alias="product_url")
    target_price: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "chatbot"


class StoreStatusResponse(BaseModel):
    """Per-store reachability snapshot for chatbot searches.

    Returned by GET /chatbot/stores so the UI (and an operator) can see which
    stores are currently worth crawling.
    """

    stores: List[StoreHealthInfo] = Field(default_factory=list)


class AuthToken(BaseModel):
    """JWT auth token passed in the Authorization header."""

    access_token: str


class ErrorResponse(BaseModel):
    """Error response model."""

    detail: str
