import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, validator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from services.api.models import Alert, Base, User
from services.common.redis_client import RedisStreamClient

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/elhaq")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TARGETS_STREAM = "stream:targets"

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Password hashing
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# JWT
security = HTTPBearer()

app = FastAPI(title="Elhaq API")

# Background task function
async def push_to_stream(target_url: str, alert_id: int):
    redis_client = await RedisStreamClient.create(REDIS_URL)
    target = {
        "url": target_url,
        "sku": f"alert_{alert_id}",
        "store": "unknown"  # or extract from URL
    }
    await redis_client.xadd(TARGETS_STREAM, {"payload": target})

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


class AlertCreate(BaseModel):
    target_url: str
    target_price: float

    @validator("target_price")
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError("Target price must be positive")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(token: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        phone: str = payload.get("sub")
        if phone is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.phone == phone).first()
    if user is None:
        raise credentials_exception
    return user


@app.post("/auth/register", response_model=Token)
def register(user: UserRegister, db: Session = Depends(get_db)):
    # Check if user exists
    db_user = db.query(User).filter(User.phone == user.phone).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Phone already registered")

    # Hash password
    hashed_password = get_password_hash(user.password)

    # Create user
    db_user = User(
        phone=user.phone,
        password_hash=hashed_password,
        salt="",  # bcrypt includes salt
        tier="free",
        valid_until=None
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.phone}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/alerts")
def create_alert(alert: AlertCreate, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Validate URL (basic)
    if not alert.target_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    # Create alert
    db_alert = Alert(
        user_id=current_user.id,
        target_url=alert.target_url,
        target_price=alert.target_price,
        active_status=True
    )
    db.add(db_alert)
    db.commit()
    db.refresh(db_alert)

    # Push to Redis stream in background
    background_tasks.add_task(push_to_stream, alert.target_url, db_alert.id)

    return {"id": db_alert.id, "message": "Alert created and target pushed to scraper"}