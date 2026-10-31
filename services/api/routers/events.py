"""First-party app event ingest: ``POST /events`` (plans/p4 WS2).

The app buffers funnel events (search, track_created, merchant_click, ...)
and posts them in batches. This router validates each batch against the
taxonomy in ``services/api/events.py`` and appends the rows to the
``app_events`` hypertable in TimescaleDB. ``services/api`` owns ingestion;
``services/analyzer`` owns the rollups, reading the same table.

The client treats ingest as fire-and-forget, so the response carries counts
only and never echoes event content back.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api.dependencies import (
    SECRET_KEY,
    get_optional_timescale_db,
    get_optional_user,
)
from services.api.events import (
    MAX_BATCH_EVENTS,
    MAX_BODY_BYTES,
    REASON_BATCH_TOO_LARGE,
    REASON_STORE_UNAVAILABLE,
    REASON_UNKNOWN_EVENT,
    EventRejected,
    unknown_event_names,
    validate_event,
)
from services.api.models import User
from services.api.monitoring.metrics import (
    APP_EVENTS_RECEIVED_TOTAL,
    APP_EVENTS_REJECTED_TOTAL,
    APP_EVENTS_STORED_TOTAL,
)
from services.common.auth import (
    TokenDecodeError,
    bearer_token,
    decode_access_token,
    token_subject,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


def _events_rate_key(request: Request) -> str:
    """Rate-limit per signed-in user, falling back to the client address.

    Behind a shared proxy every client has one address, so keying on it alone
    would let one busy install starve the rest; the token subject follows the
    user instead. The subject is a phone number, so the key carries a digest of
    it, never the number itself.
    """
    token = bearer_token(request.headers.get("Authorization"))
    if token:
        try:
            subject = token_subject(decode_access_token(token, SECRET_KEY))
        except TokenDecodeError:
            subject = None
        if subject:
            digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
            return f"user:{digest}"
    return get_remote_address(request)


limiter = Limiter(key_func=_events_rate_key)

# The client flushes at most every 30 s, so honest use is about 2/minute.
# Dynamic, so tests and ops can retune it without a code change.
EVENTS_RATE_LIMIT = os.getenv("EVENTS_RATE_LIMIT") or "60/minute"

_INSERT = (
    "INSERT INTO app_events (user_id, session_id, event, sku, store_id, "
    "category, source, channel, product_id, deal_id, item_id, event_id, "
    "properties) VALUES (:user_id, :session_id, :event, :sku, :store_id, "
    ":category, :source, :channel, :product_id, :deal_id, :item_id, "
    ":event_id, {properties})"
)


async def read_batch(request: Request) -> list[Any]:
    """Decode the request body into the list of raw event rows.

    Size limits are checked before decoding, so an oversized body costs no
    JSON parse. Each row is validated later, one at a time.

    Raises:
        HTTPException: 413 for a body over ``MAX_BODY_BYTES`` or more than
            ``MAX_BATCH_EVENTS`` rows; 400 when the body is not
            ``{"events": [...]}``.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        APP_EVENTS_REJECTED_TOTAL.labels(reason=REASON_BATCH_TOO_LARGE).inc()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"An event batch may be at most {MAX_BODY_BYTES} bytes",
        )
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        APP_EVENTS_REJECTED_TOTAL.labels(reason=REASON_BATCH_TOO_LARGE).inc()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"An event batch may be at most {MAX_BODY_BYTES} bytes",
        )
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The body must be JSON",
        ) from None
    rows = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='The body must be {"events": [...]}',
        )
    if len(rows) > MAX_BATCH_EVENTS:
        APP_EVENTS_REJECTED_TOTAL.labels(reason=REASON_BATCH_TOO_LARGE).inc()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"An event batch may hold at most {MAX_BATCH_EVENTS} events",
        )
    return rows


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda *_: EVENTS_RATE_LIMIT)
def ingest_events(
    request: Request,
    rows: list[Any] = Depends(read_batch),
    user: User | None = Depends(get_optional_user),
    ts_db: Session | None = Depends(get_optional_timescale_db),
) -> dict:
    """Store a batch of app events and report how many were accepted.

    Authentication is optional: a signed-in session's rows carry its user id,
    an anonymous browse session's rows carry only the client's session id.
    The user id always comes from the token, never from the body.

    Returns:
        ``{"accepted": n, "rejected": m}`` — counts only.

    Raises:
        HTTPException: 400 when any row names an event outside the taxonomy
            (nothing is stored), 503 when no event store is configured or
            the write fails (logged, nothing stored).
    """
    APP_EVENTS_RECEIVED_TOTAL.inc(len(rows))

    unknown = unknown_event_names(rows)
    if unknown:
        APP_EVENTS_REJECTED_TOTAL.labels(reason=REASON_UNKNOWN_EVENT).inc(len(rows))
        # Name the first offender (it is the client's own constant, not user
        # content) so a stale app build is easy to diagnose; cap its length.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown event type: {unknown[0][:40]}",
        )

    if ts_db is None:
        APP_EVENTS_REJECTED_TOTAL.labels(reason=REASON_STORE_UNAVAILABLE).inc(len(rows))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The event store is not configured",
        )

    user_id = str(user.id) if user is not None else None
    accepted: list[dict[str, Any]] = []
    rejected = 0
    for raw in rows:
        try:
            row = validate_event(raw)
        except EventRejected as exc:
            APP_EVENTS_REJECTED_TOTAL.labels(reason=exc.reason).inc()
            rejected += 1
            continue
        row["user_id"] = user_id
        row["properties"] = (
            json.dumps(row["properties"], ensure_ascii=False)
            if row["properties"] is not None
            else None
        )
        accepted.append(row)

    if accepted:
        # PostgreSQL needs the explicit JSONB cast; the SQLite test double
        # stores the serialized text as-is.
        properties = (
            "CAST(:properties AS JSONB)"
            if ts_db.get_bind().dialect.name == "postgresql"
            else ":properties"
        )
        try:
            ts_db.execute(text(_INSERT.format(properties=properties)), accepted)
            ts_db.commit()
        except Exception:
            ts_db.rollback()
            logger.exception(
                "Failed to store app events",
                extra={"rows": len(accepted)},
            )
            # Same outcome as an unconfigured store: the batch is lost, and
            # the AppEventsStoreUnavailable alert must see it.
            APP_EVENTS_REJECTED_TOTAL.labels(reason=REASON_STORE_UNAVAILABLE).inc(
                len(accepted)
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The event store is unavailable",
            ) from None
        APP_EVENTS_STORED_TOTAL.inc(len(accepted))

    return {"accepted": len(accepted), "rejected": rejected}
