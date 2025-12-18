from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session
import secrets

from services.api.models import User
from services.api.dependencies import get_db, get_password_hash, create_access_token, pwd_context, ACCESS_TOKEN_EXPIRE_MINUTES

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
        phone=user.phone,
        password_hash=hashed_password,
        salt=random_salt,
        tier="free"
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
    db_user = db.query(User).filter(User.phone == user.phone).first()
    if not db_user or not pwd_context.verify(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.phone}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}