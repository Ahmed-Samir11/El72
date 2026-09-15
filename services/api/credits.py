"""Credit system: balance, grants, and deductions.

Keyed by the canonical ``User`` (UUID). **Lazy-provisioned**: a user with no
``user_credits`` row is treated as having their tier's starting balance, so
existing users (and tests) keep working without a backfill migration.

The deduction is meant to run in the *same* session/transaction as the
operation it guards (e.g. tracker creation), so a failed deduction (402)
rolls back the caller's work cleanly.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from services.api.models import CreditTransaction, User, UserCredit

# Free users receive their initial allowance lazily. Standard and Premium are
# purchased packages, so their credits are granted by the payment flow.
TIER_STARTING_CREDITS = {
    "free": 3,
    "standard": 0,
    "premium": 0,
}
DEFAULT_STARTING_CREDITS = 3


def _starting_credits(tier: str) -> int:
    return TIER_STARTING_CREDITS.get(tier, DEFAULT_STARTING_CREDITS)


def get_balance(db: Session, user: User) -> int:
    """Return the user's current credit balance (lazy-provisioned).

    Read-only: a user with no row is reported at their tier's starting balance
    without creating a row.
    """
    credit = db.query(UserCredit).filter(UserCredit.user_id == user.id).first()
    if credit is None:
        return _starting_credits(user.tier)
    return credit.balance


def _ensure_row(db: Session, user: User) -> UserCredit:
    """Return the user's credit row, creating it (at tier balance) if missing."""
    credit = db.query(UserCredit).filter(UserCredit.user_id == user.id).first()
    if credit is None:
        credit = UserCredit(user_id=user.id, balance=_starting_credits(user.tier))
        db.add(credit)
        db.flush()
    return credit


def deduct(db: Session, user: User, amount: int = 1, reason: str = "tracker_created") -> int:
    """Deduct ``amount`` credits; raise 402 if the balance is insufficient.

    Must run in the same session/transaction as the operation it guards, so a
    failed deduction rolls back the caller's work.
    """
    if amount <= 0:
        raise ValueError("deduction amount must be positive")
    credit = _ensure_row(db, user)
    if credit.balance < amount:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient credits. Upgrade your plan to add more trackers.",
        )
    credit.balance -= amount
    db.add(CreditTransaction(user_id=user.id, amount=-amount, reason=reason))
    db.flush()
    return credit.balance


def grant(db: Session, user: User, amount: int, reason: str = "topup") -> int:
    """Grant ``amount`` credits (e.g., after a successful Paymob payment)."""
    if amount <= 0:
        raise ValueError("grant amount must be positive")
    credit = _ensure_row(db, user)
    credit.balance += amount
    db.add(CreditTransaction(user_id=user.id, amount=amount, reason=reason))
    db.flush()
    return credit.balance
