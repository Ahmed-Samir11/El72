"""Affiliate click tracking and merchant redirects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from services.api.affiliate import build_affiliate_url, store_for_url
from services.api.dependencies import get_db
from services.api.models import AffiliateClick

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


@router.get("/redirect")
def affiliate_redirect(
    target_url: str = Query(..., min_length=12, max_length=2048),
    sku: str | None = Query(default=None, max_length=255),
    deal_id: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Track a supported merchant click and redirect to its product page."""
    try:
        store_id = store_for_url(target_url)
        affiliate_url = build_affiliate_url(store_id, target_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    db.add(
        AffiliateClick(
            store_id=store_id,
            sku=sku,
            deal_id=deal_id,
            target_url=target_url,
            affiliate_url=affiliate_url,
        )
    )
    db.commit()
    return RedirectResponse(url=affiliate_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
