"""Affiliate click tracking and merchant redirects.

``GET /affiliate/redirect`` is the single choke point every departure from
the app to a merchant passes through (plans/p1 — Gate 3/4 instrumentation):
the server decides the store from the URL, writes an attributed
``affiliate_clicks`` row, and 307-redirects to the tagged merchant URL.
``GET /affiliate/config`` reports per-store affiliate-tag presence to an
admin, so "we measured zero clicks" can never silently mean "we forgot
to configure the tag".
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.affiliate import (
    AFFILIATE_TAG_ENV_VARS,
    build_affiliate_url,
    is_opaque_id,
    normalize_category,
    normalize_click_source,
    store_for_url,
    tag_presence,
)
from services.api.dependencies import get_db, get_optional_user
from services.api.models import AffiliateClick, Alert, User
from services.api.routers.payment import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/affiliate", tags=["affiliate"])

# The redirect is credential-less and takes a caller-supplied target URL
# bounded only by the merchant allowlist, so it must not become an
# open-redirect multiplier: a slowapi limiter keyed by client IP caps the
# multiplication rate (same pattern as the payment router; conftest resets
# it so per-test quotas do not accumulate).
limiter = Limiter(key_func=get_remote_address)

# A redirect is one per merchant tap, so 200/minute per client IP is far
# above any honest usage yet caps the public redirect as an open-redirect
# multiplier. Dynamic (read at request time) so tests can dial it down
# instead of firing hundreds of requests, and so ops can retune it via env
# if the limiter ever needs to follow app behaviour.
REDIRECT_RATE_LIMIT = "200/minute"


@router.get("/redirect")
@limiter.limit(lambda *_: REDIRECT_RATE_LIMIT)
def affiliate_redirect(
    request: Request,
    target_url: str = Query(..., min_length=12, max_length=2048),
    store: str | None = Query(default=None, max_length=32),
    sku: str | None = Query(default=None, max_length=255),
    deal_id: str | None = Query(default=None, max_length=255),
    category: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, max_length=32),
    session_id: str | None = Query(default=None, max_length=128),
    event_id: str | None = Query(default=None, max_length=64),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Track a supported merchant click and redirect to its product page.

    Attribution contract (AGENTS.md Critical Pattern 8): the store is derived
    from the URL server-side only; a client-supplied ``store`` that disagrees
    with the URL is a refused request, not a misattributed row; ``sku``/``deal_id``
    must be opaque ids, never URLs; the bearer token is parsed when present
    but never required (the landing page calls this too); an unconfigured tag
    passes the URL through but still logs the click.
    """
    try:
        store_id = store_for_url(target_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # A client may declare which store it believes it is opening; a claim
    # that disagrees with the URL means the caller is mislabeling (or probing)
    # the metric dimension, so the click is refused, not misattributed. A
    # blank claim is treated as "not declared", not as a mismatch.
    store_claim = (store or "").strip().lower()
    if store_claim and store_claim != store_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="store does not match the target URL's merchant host",
        )

    # A blank optional field means "not declared", not "reject": trim and
    # normalize BEFORE the opaque-id check, so honest clients that send
    # empty optional params still get their click, and stored values are
    # never whitespace-variants of the same sku (one metric value per
    # product, no split CTR).
    sku = (sku or "").strip() or None
    deal_id = (deal_id or "").strip() or None

    if not is_opaque_id(sku) or not is_opaque_id(deal_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sku and deal_id must be opaque ids, not URLs",
        )

    try:
        affiliate_url = build_affiliate_url(store_id, target_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # Category: the client's label is bounded context, never identity —
    # normalize_category drops anything outside the safe display charset
    # (markup, scheme-shaped probes) instead of storing it. When the client
    # sends none but names a sku, fill it from the server's own product
    # context; the order_by makes the fill deterministic when a sku has
    # several alert rows (arbitrary but stable, never "whichever row the
    # planner happened to reach first").
    resolved_category = normalize_category(category)
    if resolved_category is None and sku:
        resolved_category = (
            db.execute(
                select(Alert.category)
                .where(Alert.sku == sku, Alert.category.isnot(None))
                .order_by(Alert.id)
                .limit(1)
            )
            .scalars()
            .first()
        )

    db.add(
        AffiliateClick(
            store_id=store_id,
            sku=sku,
            deal_id=deal_id,
            category=resolved_category,
            source=normalize_click_source(source),
            session_id=(session_id or "").strip() or None,
            user_id=user.id if user is not None else None,
            event_id=(event_id or "").strip() or None,
            target_url=target_url,
            affiliate_url=affiliate_url,
        )
    )
    db.commit()
    return RedirectResponse(
        url=affiliate_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )


@router.get("/config")
def affiliate_config(admin=Depends(get_current_admin)) -> dict:
    """Report per-store affiliate-tag configuration (admin token only).

    A null tag must read as "no revenue path configured", never "no traffic":
    click logging still works, and this endpoint (plus the production
    startup WARNING in main.py) surfaces which stores have no monetization
    configured. Returns store_id + env var name + presence only — never
    tag values.
    """
    presence = tag_presence()
    return {
        "stores": [
            {
                "store_id": store_id,
                "env_var": AFFILIATE_TAG_ENV_VARS[store_id],
                "configured": configured,
            }
            for store_id, configured in presence.items()
        ]
    }
