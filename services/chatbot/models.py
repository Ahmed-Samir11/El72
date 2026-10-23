"""Pydantic request/response models for the chatbot service."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """A product search result from a store."""

    store_id: str
    store_name: str
    title: str
    price: float
    currency: str = "EGP"
    url: str
    image_url: Optional[str] = None
    in_stock: bool = True


class ChatMessage(BaseModel):
    """A single chat message."""

    id: int
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
    """

    session_id: Optional[UUID] = None
    user_id: Optional[int] = None
    message: str


class ChatResponse(BaseModel):
    """Response from the chatbot."""

    message: str
    session_id: UUID
    search_results: List[SearchResult] = Field(default_factory=list)


class AddToFeedRequest(BaseModel):
    """Request to add a search result to the user's feed (tracked items).

    Note: user_id is not supplied by the client; it is resolved server-side
    from the JWT token. If present, it is ignored.

    result_id may be None when the client wants to add the latest search
    result without specifying a URL.
    """

    session_id: UUID
    user_id: Optional[int] = None
    result_id: Optional[str] = None  # store_id:url hash or similar
    target_price: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "chatbot"


class AuthToken(BaseModel):
    """JWT auth token passed in the Authorization header."""

    access_token: str


class ErrorResponse(BaseModel):
    """Error response model."""

    detail: str
