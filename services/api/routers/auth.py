import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api.dependencies import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    get_db,
    get_optional_timescale_db,
    get_password_hash,
    pwd_context,
)
from services.api.models import AffiliateClick, Alert, User
from services.api.tracked_items_models import TrackedItem

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models
class UserRegister(BaseModel):
    phone: str
    password: str

    @validator("phone")
    def validate_phone(cls, v):
        if not v.startswith("+20") or len(v) != 13:
            raise ValueError("Phone must be in format +20XXXXXXXXXX")
        return v

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str


@router.post("/register", response_model=Token)
def register(user: UserRegister, db: Session = Depends(get_db)):
    # Check if user already exists
    db_user = db.query(User).filter(User.phone == user.phone).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    # Create new user
    hashed_password = get_password_hash(user.password)
    random_salt = secrets.token_hex(16)
    new_user = User(
        phone=user.phone, password_hash=hashed_password, salt=random_salt, tier="free"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Generate token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.phone}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
def login(user: UserRegister, db: Session = Depends(get_db)):
    db_user = (
        db.query(User).filter(User.phone == user.phone, User.status == "ACTIVE").first()
    )
    if not db_user or not pwd_context.verify(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.phone}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ts_db: Session | None = Depends(get_optional_timescale_db),
):
    """Anonymize the account and detach its behavior history (plans/p4 WS1).

    The ``users`` row is kept (anonymized) so foreign keys stay valid, which
    is exactly why behavior facts must be detached explicitly: their
    ``ON DELETE SET NULL`` never fires on a soft delete. The TimescaleDB
    detach runs first, so if it fails the request fails before anything is
    anonymized and the user can retry, rather than being told the account is
    gone while a funnel trail still points at it.
    """
    if ts_db is not None:
        try:
            ts_db.execute(
                text("UPDATE app_events SET user_id = NULL WHERE user_id = :uid"),
                {"uid": str(current_user.id)},
            )
            ts_db.commit()
        except Exception:
            ts_db.rollback()
            logger.exception(
                "Account deletion stopped: app_events could not be detached",
                extra={"user_id": current_user.id},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Account deletion is temporarily unavailable; try again",
            ) from None

    db.query(AffiliateClick).filter(AffiliateClick.user_id == current_user.id).update(
        {AffiliateClick.user_id: None}, synchronize_session=False
    )
    db.query(Alert).filter(Alert.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(TrackedItem).filter(TrackedItem.user_id == current_user.id).delete(
        synchronize_session=False
    )
    current_user.phone = f"deleted:{current_user.id}"
    current_user.name = "Deleted user"
    current_user.password_hash = get_password_hash(secrets.token_urlsafe(32))
    current_user.salt = secrets.token_hex(16)
    current_user.status = "DELETED"
    current_user.deleted_at = datetime.utcnow()
    current_user.valid_until = None
    db.commit()
    return None
