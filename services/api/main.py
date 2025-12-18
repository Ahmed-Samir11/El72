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
# from services.common.redis_client import RedisStreamClient

from services.api.dependencies import *

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./elhaq.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TARGETS_STREAM = "stream:targets"

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Elhaq API")

# CORS
origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "*"  # Allows all for development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from services.api.routers import auth
app.include_router(auth.router, prefix="/auth", tags=["Auth"])

# Background task function
# async def push_to_stream(target_url: str, alert_id: int):
#     redis_client = await RedisStreamClient.create(REDIS_URL)
#     target = {
#         "url": target_url,
#         "sku": f"alert_{alert_id}",
#         "store": "unknown"  # or extract from URL
#     }
#     await redis_client.xadd(TARGETS_STREAM, {"payload": target})

# Pydantic models
class AlertCreate(BaseModel):
    target_url: str
    target_price: float

    @validator("target_price")
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError("Target price must be positive")
        return v


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