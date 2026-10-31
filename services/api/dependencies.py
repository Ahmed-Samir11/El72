import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.api.models import User
from services.common.auth import (
    ALGORITHM,
    TokenDecodeError,
    decode_access_token,
    require_secret_key,
    token_subject,
)

# Configuration. The signing key has no default on purpose: a predictable
# key would let anyone forge a token for any phone number.
SECRET_KEY = require_secret_key()
ACCESS_TOKEN_EXPIRE_MINUTES = 30

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./elhaq.db")
TIMESCALE_URL = os.getenv("TIMESCALE_URL")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
TimescaleSessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=create_engine(TIMESCALE_URL))
    if TIMESCALE_URL
    else None
)

# Password hashing
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# JWT
security = HTTPBearer()

# Optional credential for surfaces that work with OR without a session (the
# affiliate redirect is one: the landing page calls it too). auto_error=False
# so a missing bearer token is None, not an automatic 403.
optional_security = HTTPBearer(auto_error=False)


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_timescale_db():
    """Yield the canonical TimescaleDB session for price-history reads."""
    if TimescaleSessionLocal is None:
        raise RuntimeError("TIMESCALE_URL is required for price-history access")
    db = TimescaleSessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: Session = Depends(get_db),
):
    """Resolve the caller's user when a valid bearer token is presented.

    Attribution without authentication: a click from a signed-in app user is
    attributed by user_id; a click from the landing page or any token-less
    caller is still logged with user_id NULL. Malformed/expired tokens are
    deliberately NOT an error here — rejecting them would turn attribution
    into an auth wall on a public redirect. Never returns a phone number; the
    User row's id is all that reaches affiliate_clicks.
    """
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials, SECRET_KEY)
    except TokenDecodeError:
        return None
    phone = token_subject(payload)
    if phone is None:
        return None
    return db.query(User).filter(User.phone == phone, User.status == "ACTIVE").first()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    secret_key: Optional[str] = None,
):
    """Sign a JWT. Defaults to the user-facing SECRET_KEY; callers that issue
    tokens for a separate credential domain (e.g. admin tokens) MUST pass
    their own secret explicitly so the two token spaces never share a key.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # 7-day access token. There is no refresh-token flow in this MVP, so a
        # short 15-minute expiry caused every authenticated request to 401
        # shortly after login.
        expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, secret_key or SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token.credentials, SECRET_KEY)
    except TokenDecodeError:
        raise credentials_exception from None
    phone = token_subject(payload)
    if phone is None:
        raise credentials_exception
    user = db.query(User).filter(User.phone == phone, User.status == "ACTIVE").first()
    if user is None:
        raise credentials_exception
    return user
