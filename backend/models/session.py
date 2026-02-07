"""
In-memory session state — one per conversation.
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from backend.models.product import Product
from backend.models.shopping import Cart, ShoppingSpec


class UserSession(BaseModel):
    """Everything we need for a single shopping conversation."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    spec: ShoppingSpec = Field(default_factory=ShoppingSpec)
    cart: Cart = Field(default_factory=Cart)
    search_results: dict[str, list[Product]] = Field(default_factory=dict)
    """category -> list of ranked products"""

    def model_post_init(self, __context) -> None:
        self.cart.session_id = self.session_id


# ---------------------------------------------------------------------------
# Global in-memory store (keyed by session_id)
# ---------------------------------------------------------------------------

_sessions: dict[str, UserSession] = {}


def get_or_create_session(session_id: Optional[str] = None) -> UserSession:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    sess = UserSession() if session_id is None else UserSession(session_id=session_id)
    _sessions[sess.session_id] = sess
    return sess


def get_session(session_id: str) -> Optional[UserSession]:
    return _sessions.get(session_id)
