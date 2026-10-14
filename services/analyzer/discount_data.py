"""DB-backed data loading for the fake-discount detector.

This module turns raw ``price_history`` rows into the inputs the pure
:func:`services.analyzer.fake_discount.detect_fake_discount` function expects.

Keying convention (production): ``sku`` is the canonical product id and
``store_id`` is a separate column, so one product spans multiple ``store_id``
rows. ``store_id`` is optional — when omitted the detector pools all stores.

The module is deliberately thin: it runs one query for the 90-day window and
does the windowing/median/low math in Python so the logic is unit-testable
with a mocked connection (no live Postgres required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, List, Mapping, Optional, Sequence

# Minimum number of price points in the 90-day window before we trust the
# baseline. Below this we report "insufficient_history" instead of guessing.
DEFAULT_MIN_POINTS = 14
DEFAULT_HISTORY_DAYS = 90
DEFAULT_RECENT_DAYS = 30


@dataclass
class DiscountInputs:
    """Everything the fake-discount detector needs for one product."""

    sku: str
    store_id: Optional[str]
    status: str  # "ok" | "insufficient_history"
    current_price: Optional[float] = None
    historical_prices: List[float] = field(default_factory=list)
    median_30d: Optional[float] = None
    median_90d: Optional[float] = None
    historical_low: Optional[float] = None
    advertised_reference_price: Optional[float] = None
    competitor_prices: List[float] = field(default_factory=list)
    recent_prices: List[float] = field(default_factory=list)
    point_count: int = 0


def _median_or_none(values: Sequence[float]) -> Optional[float]:
    return median(values) if values else None


def build_discount_inputs(
    rows: Sequence[Mapping[str, Any]],
    sku: str,
    store_id: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
    recent_days: int = DEFAULT_RECENT_DAYS,
    min_points: int = DEFAULT_MIN_POINTS,
) -> DiscountInputs:
    """Compute :class:`DiscountInputs` from already-fetched price rows.

    ``rows`` are mappings with keys ``time`` (datetime), ``store_id`` (str),
    ``price_local`` (float/Decimal), and ``advertised_price`` (float/Decimal
    or None), ordered by ``time`` ascending.

    Splitting this out from the async fetch makes the windowing/median/low
    math directly unit-testable without a database.
    """
    now = now or datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=recent_days)

    # Focus rows: the target store when given, otherwise all stores pooled.
    focus = [r for r in rows if store_id is None or r.get("store_id") == store_id]

    def _price(r: Mapping[str, Any]) -> float:
        return float(r["price_local"])

    historical_prices = [_price(r) for r in focus]
    recent_rows = [r for r in focus if r["time"] >= recent_cutoff]
    recent_prices = [_price(r) for r in recent_rows]

    current_price = historical_prices[-1] if historical_prices else None
    historical_low = min(historical_prices) if historical_prices else None
    median_90d = _median_or_none(historical_prices)
    median_30d = _median_or_none(recent_prices)

    # Latest non-null advertised "was" price in the focus window.
    advertised_reference_price: Optional[float] = None
    for r in reversed(focus):
        adv = r.get("advertised_price")
        if adv is not None:
            advertised_reference_price = float(adv)
            break

    # Competitor prices: the most recent price from each *other* store.
    competitor_prices: List[float] = []
    if store_id is not None:
        latest_by_store: dict = {}
        for r in rows:
            sid = r.get("store_id")
            if sid is None or sid == store_id:
                continue
            # rows are time-ascending, so the last seen per store is latest.
            latest_by_store[sid] = _price(r)
        competitor_prices = list(latest_by_store.values())

    point_count = len(historical_prices)
    status = "ok" if point_count >= min_points else "insufficient_history"

    return DiscountInputs(
        sku=sku,
        store_id=store_id,
        status=status,
        current_price=current_price,
        historical_prices=historical_prices,
        median_30d=median_30d,
        median_90d=median_90d,
        historical_low=historical_low,
        advertised_reference_price=advertised_reference_price,
        competitor_prices=competitor_prices,
        recent_prices=recent_prices,
        point_count=point_count,
    )


async def load_discount_inputs(
    conn: Any,
    sku: str,
    store_id: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
    recent_days: int = DEFAULT_RECENT_DAYS,
    min_points: int = DEFAULT_MIN_POINTS,
) -> DiscountInputs:
    """Fetch the 90-day window for ``sku`` and build :class:`DiscountInputs`.

    ``conn`` is an asyncpg connection (or a mock exposing ``fetch``).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=history_days)
    rows = await conn.fetch(
        "SELECT time, store_id, price_local, advertised_price "
        "FROM price_history WHERE sku = $1 AND time >= $2 ORDER BY time",
        sku,
        cutoff,
    )
    return build_discount_inputs(
        rows,
        sku,
        store_id,
        now=now,
        history_days=history_days,
        recent_days=recent_days,
        min_points=min_points,
    )
