"""Alert-surface endpoints: read the alert feed, record that it was opened.

``GET /alerts/recent``  — the user's alert-event history (the Alerts tab), and
``POST /alerts/{id}/open`` — the ``alert_opened`` evidence (report §23 fields,
plan p2 WS1.3). Without the second one Gate 2 (\"do alerts bring users back?\")
is unreadable: an event that was only WRITTEN is not an event the user SAW.

This router is deliberately separate from ``POST /alerts`` (kept in
``main.py``): that endpoint CREATES a tracker (the historical meaning of an
\"alert\" row), which is a different object from an alert EVENT.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.api.dependencies import get_current_user, get_db
from services.api.models import AlertEvent, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])

# Auth-gated, but still a per-client quota so a leaked token cannot turn the
# alert feed into an unbounded read amplifier (same pattern as the affiliate
# redirect: dynamic limit string so tests can dial it down instead of firing
# hundreds of requests).
limiter = Limiter(key_func=get_remote_address)
ALERTS_READ_RATE_LIMIT = os.getenv("ALERTS_READ_RATE_LIMIT") or "120/minute"
ALERTS_OPEN_RATE_LIMIT = os.getenv("ALERTS_OPEN_RATE_LIMIT") or "120/minute"

# Bounded by the server, not the client: the Alerts tab is a feed, and an
# unbounded ``limit`` would turn a per-user read into a table scan.
MAX_ALERTS_LIMIT = 200
DEFAULT_ALERTS_LIMIT = 50

# Accepted shapes for ``since``: a calendar date or an ISO timestamp. Parsed
# here rather than by Pydantic so an invalid value can produce this router's
# own 400 instead of a framework error page.
_SINCE_LENGTH = 40


def _to_iso(value: datetime | None) -> str | None:
    """Normalize a stored timestamp to a clean ISO-8601 string, or null.

    SQLite returns TIMESTAMP values as strings and PostgreSQL returns datetimes;
    the client distinguishes \"seen\" from \"never seen\" by null-or-not, so both
    backends must agree on the shape.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.replace(microsecond=0).isoformat()
    text = str(value).strip().replace(" ", "T", 1)
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _parse_since(raw: str | None) -> datetime | None:
    """Parse the optional ``since`` filter, refusing anything unparseable.

    Accepts ``YYYY-MM-DD`` and ISO timestamps (a trailing ``Z`` is normalized
    away because ``created_at`` is stored as naive UTC; keeping the offset would
    compare two different kinds of timestamp).
    """
    if not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since must be a calendar date or ISO timestamp",
        ) from None


def _event_id_value(raw: str, dialect_name: str) -> int | uuid.UUID | None:
    """Coerce a path id to the type this deployment's primary key uses.

    ``alert_events.id`` is a native UUID on PostgreSQL and an integer on the
    SQLite dev/test engine (DialectIdType). Binding the wrong type is refused
    BEFORE the query: psycopg2 raises on an integer against a UUID column, and
    that would surface as a server bug rather than as \"that id is not yours\".
    """
    if dialect_name == "sqlite":
        return int(raw) if raw.isdigit() else None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


@router.get("/alerts/recent")
@limiter.limit(lambda *_: ALERTS_READ_RATE_LIMIT)
def alerts_recent(
    request: Request,
    limit: int = Query(DEFAULT_ALERTS_LIMIT, ge=1, le=MAX_ALERTS_LIMIT),
    since: str | None = Query(default=None, min_length=4, max_length=_SINCE_LENGTH),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the caller's alert events, newest first, plus how many are unopened.

    Auth-gated and scoped to the caller's own rows: the query filters on
    ``user_id`` rather than trusting the client to ask politely. ``unopened_total``
    travels with the feed so the \"N newer alerts\" badge needs no second round
    trip, and it counts unopened events for THIS user only.
    """
    since_value = _parse_since(since)

    conditions = [AlertEvent.user_id == current_user.id]
    if since_value is not None:
        conditions.append(AlertEvent.created_at >= since_value)

    rows = (
        db.execute(
            select(AlertEvent)
            .where(*conditions)
            .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    unopened_total = db.execute(
        select(func.count(AlertEvent.id)).where(
            AlertEvent.user_id == current_user.id,
            AlertEvent.opened_at.is_(None),
        )
    ).scalar_one()

    return {
        "alerts": [
            {
                "id": str(row.id),
                "tracked_item_id": row.tracked_item_id,
                "sku": row.sku,
                "store_id": row.store_id,
                "category": row.category,
                "url": row.url,
                "event_type": row.event_type,
                "price_egp": _number(row.price_egp),
                "reference_price_egp": _number(row.reference_price_egp),
                "discount_pct": _number(row.discount_pct),
                "channel": row.channel,
                "created_at": _to_iso(row.created_at),
                "opened_at": _to_iso(row.opened_at),
            }
            for row in rows
        ],
        "unopened_total": unopened_total,
        "limit": limit,
    }


@router.post("/alerts/{event_id}/open")
@limiter.limit(lambda *_: ALERTS_OPEN_RATE_LIMIT)
def open_alert(
    request: Request,
    event_id: str = Path(..., min_length=1, max_length=64),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Record that the caller has seen one of THEIR OWN alert events.

    Idempotent: a second tap keeps the first ``opened_at`` (an alert the user
    re-reads must not look like a fresh return), and the response says so.
    Another user's id and a nonexistent id both answer 404, so the endpoint
    cannot be used to probe which event ids exist.
    """
    ident = _event_id_value(event_id, db.get_bind().dialect.name)
    if ident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert event not found",
        )

    row = db.execute(
        select(AlertEvent)
        .where(AlertEvent.id == ident, AlertEvent.user_id == current_user.id)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert event not found"
        )

    already_open = row.opened_at is not None
    if not already_open:
        # UTC naive, matching the column convention the rest of services/api
        # uses; the schema's updated_at trigger handles updated_at itself.
        row.opened_at = datetime.utcnow()
        db.commit()
    else:
        db.commit()  # releases the read transaction; nothing was written

    logger.info(
        "Alert event opened",
        extra={
            "user_id": current_user.id,
            "event_id": str(row.id),
            "already_open": already_open,
        },
    )

    return {
        "id": str(row.id),
        "opened_at": _to_iso(row.opened_at),
        "already_open": already_open,
    }


def _number(value: Any) -> float | None:
    """Render a Numeric column as JSON-safe number or null (never Decimal-in-JSON)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
