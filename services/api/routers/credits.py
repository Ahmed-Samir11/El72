"""Credit balance endpoints (auth required)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from services.api.credits import get_balance
from services.api.dependencies import get_current_user, get_db
from services.api.models import CreditTransaction, User

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("/balance")
def get_credit_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the current user's credit balance and tier."""
    return {"balance": get_balance(db, current_user), "tier": current_user.tier}


@router.get("/transactions")
def get_credit_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    """Return the user's credit ledger, most recent first."""
    rows = (
        db.query(CreditTransaction)
        .filter(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(t.id),
            "amount": t.amount,
            "reason": t.reason,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]
