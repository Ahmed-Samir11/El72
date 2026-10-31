"""Per-store availability tracking for chatbot search.

Two problems this solves:

* the user could not tell "this store has nothing matching" from "this store
  is unreachable" — every failure was an empty list;
* a blocked store (Cloudflare challenge, HTTP/2 reset, dead DNS) was re-crawled
  on every message, burning crawl time and, worse, an LLM slot.

The tracker records an explicit state per store and puts a store that keeps
failing on a cooldown, during which it is skipped and reported as ``cooling``
instead of being crawled again.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

# How long a store stays skipped after crossing the failure threshold.
STORE_COOLDOWN_SECONDS = float(os.getenv("STORE_COOLDOWN_SECONDS", "600"))
# Consecutive non-ok results before a store is put on cooldown.
STORE_FAILURE_THRESHOLD = int(os.getenv("STORE_FAILURE_THRESHOLD", "3"))

# Machine-readable store states, surfaced verbatim to the client.
STATE_OK = "ok"
STATE_EMPTY = "empty"  # reachable, but nothing on this page matched
STATE_BLOCKED = "blocked"  # anti-bot / HTTP error / dead domain
STATE_TIMEOUT = "timeout"
STATE_ROBOTS_DENIED = "robots_denied"
STATE_COOLING = "cooling"  # skipped because it keeps failing
STATE_CACHED = "cached"  # answered from the search cache

_OK_STATES = {STATE_OK, STATE_EMPTY, STATE_CACHED}


@dataclass
class StoreStatus:
    """One store's outcome for one search, ready to serialize."""

    store_id: str
    state: str
    products: int = 0
    detail: str = ""

    def as_dict(self) -> Dict[str, object]:
        """JSON-safe form for the chatbot response and ``/chatbot/stores``."""
        return {
            "store_id": self.store_id,
            "state": self.state,
            "products": self.products,
            "detail": self.detail,
        }


class StoreHealth:
    """Tracks each store's recent outcomes and its cooldown window."""

    def __init__(
        self,
        cooldown_seconds: float = STORE_COOLDOWN_SECONDS,
        failure_threshold: int = STORE_FAILURE_THRESHOLD,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = max(1, failure_threshold)
        self._failures: Dict[str, int] = {}
        self._cooling_until: Dict[str, float] = {}
        self._last: Dict[str, StoreStatus] = {}

    def is_cooling(self, store_id: str) -> bool:
        """Whether [store_id] should be skipped for this search."""
        until = self._cooling_until.get(store_id)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        # Window expired: give the store one more chance.
        del self._cooling_until[store_id]
        self._failures[store_id] = 0
        return False

    def record(
        self,
        store_id: str,
        state: str,
        products: int = 0,
        detail: str = "",
    ) -> StoreStatus:
        """Log one outcome and return the status to report.

        Crossing the failure threshold starts the cooldown; any ok/empty/cached
        result clears the failure streak.
        """
        status = StoreStatus(
            store_id=store_id, state=state, products=products, detail=detail
        )
        self._last[store_id] = status

        if state in _OK_STATES:
            self._failures[store_id] = 0
            self._cooling_until.pop(store_id, None)
            return status

        failures = self._failures.get(store_id, 0) + 1
        self._failures[store_id] = failures
        if failures >= self.failure_threshold:
            self._cooling_until[store_id] = time.monotonic() + self.cooldown_seconds
            logger.warning(
                "Store %s failed %d times; skipping for %ss",
                store_id,
                failures,
                int(self.cooldown_seconds),
            )
        return status

    def mark_cooling(self, store_id: str) -> StoreStatus:
        """The status to report when a store was skipped, not crawled."""
        remaining = max(
            0.0, round(self._cooling_until.get(store_id, 0.0) - time.monotonic())
        )
        return StoreStatus(
            store_id=store_id,
            state=STATE_COOLING,
            detail=f"skipped for {int(remaining)}s after repeated failures",
        )

    def snapshot(self) -> List[Dict[str, object]]:
        """Last known state for every store seen, for ``/chatbot/stores``."""
        return [status.as_dict() for status in self._last.values()]

    def reset(self) -> None:
        """Forget all state (used by tests and by an operator-triggered retry)."""
        self._failures.clear()
        self._cooling_until.clear()
        self._last.clear()
