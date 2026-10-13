"""Recurring subscription endpoints (Paymob subscriptions, Feature 7).

- ``POST /subscription/create`` — create a subscription (first charge +
  recurring mandate). Bearer-authenticated; the client never sets the amount
  (server-determined from the package, plan 7.1).
- ``POST /subscription/cancel`` — cancel the subscription (owner only, plan
  7.1/7.4).
- ``GET  /subscription/status`` — the user's active subscription.

Only Paymob tokens cross the wire; card data never reaches us (PCI-DSS
requirement 7.1). The staging-token consumption, payment-method creation,
and audit helpers are reused from :mod:`services.api.routers.payment`.
"""

import logging
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.api.dependencies import get_current_user, get_db
from services.api.models import User
from services.api.payment_security import record_payment_event, sanitize_for_log
from services.api.routers.payment import (
    _client_ip,
    _consume_staging_token,
    _utcnow,
)
from services.api.staging_store import get_staging_store
from services.api.subscription_models import Subscription
from services.common.paymob_client import (
    PaymobApiError,
    cancel_subscription,
    create_payment_method,
    create_subscription,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscriptions"])

# Server-determined pricing (the client never sets the amount, plan 7.1).
PACKAGE_PRICING = {"standard": 30.0, "premium": 90.0}
PACKAGE_PRICES_PAISA = {"standard": 3000, "premium": 9000}

# A user may have at most one active subscription at a time.
ONE_ACTIVE_SUBSCRIPTION = True


class SubscriptionCreateBody(BaseModel):
    staging_token: str
    token: str
    package: str = Field(pattern="^(standard|premium)$")
    interval: str = Field(default="month", pattern="^month$")


class SubscriptionCancelBody(BaseModel):
    subscription_id: str


class SubscriptionCreateResponse(BaseModel):
    subscription_id: str
    next_charge: str


class SubscriptionCancelResponse(BaseModel):
    status: str
    effective: str


class SubscriptionStatusResponse(BaseModel):
    active: bool
    package: Optional[str] = None
    next_charge: Optional[str] = None


def _paymob_subscription_id(resp: dict) -> str:
    """Pull the Paymob subscription id out of a create-subscription response."""
    sub_id = resp.get("id")
    if isinstance(sub_id, (str, int)) and str(sub_id).strip():
        return str(sub_id).strip()
    raise HTTPException(
        status_code=502, detail="Payment provider did not return a subscription id"
    )


@router.post("/subscription/create", response_model=SubscriptionCreateResponse)
def create_subscription_endpoint(
    body: SubscriptionCreateBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a recurring subscription (first charge + monthly mandate).

    The staging token is atomically consumed (single-use) and must be bound
    to the authenticated user (plan 7.1). The monthly amount is
    server-determined from the package — the client never sets it.
    """
    if not body.token:
        raise HTTPException(status_code=400, detail="Missing tokenization token")

    # One active subscription per user (plan 7.1).
    existing = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == str(user.id),
            Subscription.status == "active",
        )
        .first()
    )
    if existing is not None and ONE_ACTIVE_SUBSCRIPTION:
        raise HTTPException(
            status_code=409, detail="An active subscription already exists"
        )

    store = get_staging_store()
    _consume_staging_token(store, body.staging_token, user, request, db)

    now = _utcnow()
    next_charge = now + timedelta(days=30)
    reference_id = f"elhaq-sub-{user.id}-{body.package}"
    try:
        method = create_payment_method(body.token, "card")
        sub_resp = create_subscription(
            method["id"],
            PACKAGE_PRICES_PAISA[body.package],
            "EGP",
            reference_id,
            interval=body.interval,
        )
    except PaymobApiError as exc:
        _paymob_error_response(exc)

    subscription_id = _paymob_subscription_id(sub_resp)
    subscription = Subscription(
        id=str(uuid.uuid4()),
        user_id=user.id,
        paymob_subscription_id=subscription_id,
        card_payment_method_id=method["id"],
        package=body.package,
        amount_egp=PACKAGE_PRICING[body.package],
        interval=body.interval,
        status="active",
        failed_renewals=0,
        next_charge=next_charge,
    )
    db.add(subscription)
    # Credits are NOT granted here: the first charge is confirmed by the
    # renewal webhook (Feature 7), which grants credits on success. Granting
    # at creation would credit the user before the charge is confirmed
    # (review finding: premature credit granting).
    record_payment_event(
        db,
        event_type="subscription_created",
        user_id=str(user.id),
        payment_ref=subscription_id,
        detail=sanitize_for_log(f"package={body.package}"),
        ip_address=_client_ip(request),
    )
    db.commit()

    logger.info(
        "Subscription %s created for user %s (%s)",
        subscription_id,
        user.id,
        body.package,
    )
    # Return the internal id (not the Paymob id) so the client references
    # the subscription by our id in /subscription/cancel and
    # /subscription/status.
    return SubscriptionCreateResponse(
        subscription_id=subscription.id,
        next_charge=next_charge.isoformat(),
    )


@router.post("/subscription/cancel", response_model=SubscriptionCancelResponse)
def cancel_subscription_endpoint(
    body: SubscriptionCancelBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel the user's subscription (owner only, plan 7.1/7.4).

    Cancellation is immediate and effective at the end of the current
    billing period.
    """
    subscription = (
        db.query(Subscription).filter(Subscription.id == body.subscription_id).first()
    )
    if subscription is None or subscription.user_id != str(user.id):
        # Do not reveal whether the id exists for another user.
        raise HTTPException(status_code=404, detail="Subscription not found")
    if subscription.status != "active":
        raise HTTPException(status_code=400, detail="Subscription is not active")

    try:
        cancel_subscription(subscription.paymob_subscription_id)
    except PaymobApiError as exc:
        _paymob_error_response(exc)

    now = _utcnow()
    # Cancellation is effective at the end of the current billing period
    # (plan 7.4): the user is not charged again after ``next_charge``.
    effective = subscription.next_charge
    subscription.status = "canceled"
    subscription.canceled_at = now
    record_payment_event(
        db,
        event_type="subscription_canceled",
        user_id=str(user.id),
        payment_ref=subscription.paymob_subscription_id,
        detail=sanitize_for_log("reason=user_canceled"),
        ip_address=_client_ip(request),
    )
    db.commit()

    logger.info(
        "Subscription %s canceled by user %s",
        subscription.paymob_subscription_id,
        user.id,
    )
    return SubscriptionCancelResponse(
        status="canceled", effective=effective.isoformat()
    )


@router.get("/subscription/status", response_model=SubscriptionStatusResponse)
def get_subscription_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the user's active subscription (plan 7)."""
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == str(user.id),
            Subscription.status == "active",
        )
        .first()
    )
    if subscription is None:
        return SubscriptionStatusResponse(active=False)
    return SubscriptionStatusResponse(
        active=True,
        package=subscription.package,
        next_charge=subscription.next_charge.isoformat(),
    )


def _paymob_error_response(exc: PaymobApiError) -> None:
    """Map a Paymob API error to a controlled HTTP response."""
    if exc.status_code == 400:
        raise HTTPException(status_code=400, detail=exc.detail)
    raise HTTPException(status_code=502, detail="Payment provider error")
