"""Pydantic request/response models for the chatbot service."""

from datetime import datetime
from typing import List, Optional

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
    session_id: int
    role: str  # 'user' or 'bot'
    content: str
    created_at: datetime


class ChatSession(BaseModel):
    """A chat session with its messages."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Request to send a message to the chatbot."""

    session_id: int
    user_id: int
    message: str


class ChatResponse(BaseModel):
    """Response from the chatbot."""

    message: str
    session_id: int
    search_results: List[SearchResult] = Field(default_factory=list)


class AddToFeedRequest(BaseModel):
    """Request to add a search result to the user's feed (tracked items)."""

    session_id: int
    user_id: int
    result_id: str  # store_id:url hash or similar
    target_price: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "chatbot"