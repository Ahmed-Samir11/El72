"""Fair-use limits for tracker creation (plans/p3-free-tracker-model-alignment.md).

The shipped business model is **free tracking bounded by fair use**, not tracking
gated behind a payment decision (strategy report §2 new hypothesis, §27 final
recommendation, §24 priority 9: "Anti-abuse/rate limiting — protects the free
tracker economics"). This module is the enforcement point that stands in front
of tracker creation, and it is the single source of truth for the enforcement
mode, which three env variables control:

- ``CREDITS_ENFORCEMENT=fair_use`` (default): creation never touches the credit
  ledger. Two bounds apply instead — a per-user **active-tracker cap**
  (``FAIR_USE_MAX_TRACKERS``, default 100, which mirrors the ceiling the free
  tier already had in practice) and a **minimum gap between creations**
  (3 s). Exceeding the cap is ``409`` with a structured detail; creating too
  fast is ``429`` with a ``Retry-After`` header.
- ``CREDITS_ENFORCEMENT=on``: the legacy ledger — :func:`services.api.credits.deduct`
  still runs and still answers ``402`` when the balance is empty.
- ``CREDITS_ENFORCEMENT=off``: no bound at all (dev and test harnesses).

Both refusals carry a **structured** detail (``{code, active_trackers, cap}``
and ``{code, retry_after_seconds}``) because the client must never parse prose:
the number it shows on a device comes from here, and a reworded sentence must
not be able to break a UI branch.

The ledger tables (``user_credits`` / ``credit_transactions``) are untouched:
a future premium tier, if the launch economics earn one, reuses them as-is.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from services.api import credits
from services.api.dependencies import get_current_user, get_db
from services.api.models import User
from services.api.tracked_items_models import TrackedItem

logger = logging.getLogger(__name__)

# Modes. ``fair_use`` is the default: a release build that forgets to configure
# the variable must never fall back into payment friction.
FAIR_USE = "fair_use"
LEGACY_CREDITS = "on"
DISABLED = "off"
ENFORCEMENT_MODES = (FAIR_USE, LEGACY_CREDITS, DISABLED)
DEFAULT_ENFORCEMENT = FAIR_USE

CREDITS_ENFORCEMENT_ENV = "CREDITS_ENFORCEMENT"
MAX_TRACKERS_ENV = "FAIR_USE_MAX_TRACKERS"
PAYMENTS_ENABLED_ENV = "PAYMENTS_ENABLED"

# 100 is not invented scarcity: it is the value the free tier already resolved
# to (credits.TIER_STARTING_CREDITS["free"]), so the cap cannot take capability
# away from anyone who has an account today. Ops may raise or lower it.
DEFAULT_MAX_TRACKERS = 100

# Minimum gap between creations, in seconds. Chosen to bound scraper fan-out
# and notification volume per session rather than to stop a real user: nobody
# adds trackers faster than one per three seconds by hand.
MIN_CREATION_INTERVAL_SECONDS = 3.0

# Process-local creation throttle, keyed by user id. Same shape as the
# refresh throttle in tracked_items_api: MVP runs a single API instance, and
# a multi-worker deployment would move this to Redis. It bounds hammering
# within a process, which is what a v1 deployment is.
_last_creation_at: dict[str, datetime] = {}

router = APIRouter()


def _now() -> datetime:
    """Current wall-clock time, aware UTC.

    Patched by tests. Kept separate from the naive-UTC ``created_at``
    columns on purpose: the rate window compares aware values, and mixing
    the two kinds is what would raise in production while SQLite tests stayed
    green.
    """
    return datetime.now(timezone.utc)


def enforcement_mode() -> str:
    """Return the credit/fair-use enforcement mode for this process.

    Reads the environment on every call so a deployment (and a test) can
    change it without re-importing. An unrecognized value never silently
    picks the strictest mode: it is logged and ``fair_use`` is used.
    """
    raw = os.getenv(CREDITS_ENFORCEMENT_ENV, DEFAULT_ENFORCEMENT).strip().lower()
    if raw in ENFORCEMENT_MODES:
        return raw
    logger.warning(
        "Ignoring an unrecognized CREDITS_ENFORCEMENT value; using the default",
        extra={
            "value": raw[:40],
            "accepted": list(ENFORCEMENT_MODES),
            "used": DEFAULT_ENFORCEMENT,
        },
    )
    return DEFAULT_ENFORCEMENT


def payments_surface_enabled() -> bool:
    """Whether the Paymob payment and subscription routers may be mounted.

    Off unless an operator asks for it explicitly, or the legacy credit
    model is the enforcement mode (in which case the app still needs a way
    to buy credits). The default release backend therefore registers no
    payment surface at all: no endpoint, no OpenAPI entry, no attack surface.
    """
    if os.getenv(PAYMENTS_ENABLED_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    return enforcement_mode() == LEGACY_CREDITS


def max_trackers() -> int:
    """Per-user active-tracker cap (``FAIR_USE_MAX_TRACKERS``).

    A non-numeric, zero or negative value is a configuration mistake, not a
    license to track without limit: it is logged and the default applies.
    """
    raw = os.getenv(MAX_TRACKERS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_TRACKERS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring a non-integer FAIR_USE_MAX_TRACKERS value; using the default",
            extra={"value": raw[:20], "used": DEFAULT_MAX_TRACKERS},
        )
        return DEFAULT_MAX_TRACKERS
    if value <= 0:
        logger.warning(
            "Ignoring a non-positive FAIR_USE_MAX_TRACKERS value; using the default",
            extra={"value": value, "used": DEFAULT_MAX_TRACKERS},
        )
        return DEFAULT_MAX_TRACKERS
    return value


def active_tracker_count(db: Session, user: User) -> int:
    """Count the user's active trackers — the number the cap is applied to.

    Inactive (deleted/paused) trackers are not counted, which is what makes
    "delete one to make room" a real affordance in the client rather than a
    dead end.
    """
    return int(
        db.query(func.count(TrackedItem.id))
        .filter(TrackedItem.user_id == user.id, TrackedItem.is_active.is_(True))
        .scalar()
        or 0
    )


def last_created_at(db: Session, user: User) -> Optional[datetime]:
    """Naive-UTC ``created_at`` of the user's most recent active tracker.

    Stored naive because that is what the column is (TIMESTAMP WITHOUT
    TIME ZONE); :func:`_iso_utc` is the only place that adds the marker.
    """
    value = (
        db.query(func.max(TrackedItem.created_at))
        .filter(TrackedItem.user_id == user.id, TrackedItem.is_active.is_(True))
        .scalar()
    )
    return value if value else None


def seconds_until_next_creation(user: User) -> float:
    """Seconds still to wait before the next tracker creation is allowed.

    ``0.0`` means the next creation may proceed (including for a user who has
    never created one in this process).
    """
    last = _last_creation_at.get(str(user.id))
    if last is None:
        return 0.0
    elapsed = (_now() - last).total_seconds()
    return max(0.0, MIN_CREATION_INTERVAL_SECONDS - elapsed)


def reset_creation_times() -> None:
    """Drop the process-local creation throttle.

    Used by the test harness for the same reason it resets the slowapi
    limiters: the state is module-level and every test shares it otherwise.
    """
    _last_creation_at.clear()


def enforce_tracker_creation(db: Session, user: User) -> None:
    """Refuse a tracker creation the configured enforcement mode forbids.

    Called **before** anything is written, so a refusal leaves no partial row
    and no credit is burned. Under ``on`` the ledger deduction runs here,
    in the caller's session/transaction, exactly as before.
    """
    mode = enforcement_mode()
    if mode == DISABLED:
        return
    if mode == LEGACY_CREDITS:
        credits.deduct(db, user, amount=1, reason="tracker_created")
        return

    wait = seconds_until_next_creation(user)
    # A refused attempt also counts as an attempt: a client hammering a
    # capped or throttled user must not be able to probe for free.
    _last_creation_at[str(user.id)] = _now()
    if wait > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "creation_rate_limit",
                "retry_after_seconds": round(wait, 2),
            },
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )

    cap = max_trackers()
    active = active_tracker_count(db, user)
    if active >= cap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "fair_use_cap",
                "active_trackers": active,
                "cap": cap,
            },
        )


def usage_payload(db: Session, user: User) -> dict:
    """Build the ``GET /usage/limits`` payload.

    This replaces "credits remaining" wherever the app shows an account
    state, and is what P4's rollups read for trackers-per-user. ``cap`` is
    ``null`` when fair use is not the mode, so the client cannot render a
    ceiling that the server is not enforcing.
    """
    mode = enforcement_mode()
    created = last_created_at(db, user)
    return {
        "enforcement": mode,
        "active_trackers": active_tracker_count(db, user),
        "cap": max_trackers() if mode == FAIR_USE else None,
        "created_last": _iso_utc(created),
        "retry_after_seconds": round(seconds_until_next_creation(user), 2),
    }


def _iso_utc(created: Optional[datetime]) -> Optional[str]:
    """Render a naive-UTC timestamp as ISO-8601 with an explicit UTC marker."""
    if created is None:
        return None
    return created.replace(tzinfo=None).isoformat() + "Z"


@router.get("/usage/limits")
def get_usage_limits(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Report the caller's fair-use state: ``GET /usage/limits``.

    Auth required — this is per-user state, not a public stat. It answers
    the only limit question the free model asks ("how many of my allowed
    trackers am I using, and when may I create the next one?") without ever
    putting a price on a tracker.
    """
    return usage_payload(db, current_user)
