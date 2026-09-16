import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, validator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from services.api.models import Alert, Base, User
from services.api.tracked_items_models import Base as TrackedBase
from services.common.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)

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
TrackedBase.metadata.create_all(bind=engine)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Elhaq API")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

# Public demo endpoints (no auth) consumed by the landing page and Flutter app:
# /stats, /deals/live, /price-history/{sku}, /pricing.
from services.api.routers import public_api
app.include_router(public_api.router)

# Credit balance endpoints (auth required): /credits/balance, /credits/transactions.
from services.api.routers import credits as credits_router
app.include_router(credits_router.router)

# Affiliate click tracking and safe merchant redirects.
from services.api.routers import affiliate as affiliate_router
app.include_router(affiliate_router.router)

# Tracked-item lifecycle, including one-credit deduction per new tracker.
from services.api.tracked_items_api import router as tracked_items_router
app.include_router(tracked_items_router)

# Demo mode: seed realistic demo data on startup (idempotent).
# Toggle with DEMO_MODE=True (default) for the investor demo.
DEMO_MODE = os.getenv("DEMO_MODE", "True").lower() in ("1", "true", "yes", "on")


@app.on_event("startup")
def _seed_demo_data_on_startup() -> None:
    if not DEMO_MODE:
        return
    try:
        from services.api.seed_demo_data import run_seed
        summary = run_seed(engine=engine)
        logger.info("Demo data seeded on startup", extra={"summary": summary})
    except Exception as e:  # fail-soft: demo data is non-critical
        logger.exception("Demo seed failed; continuing", extra={"error": str(e)})

# Background task function to push new alert targets to scraper stream
async def push_to_stream(target_url: str, alert_id: int):
    """Push new alert target to Redis stream for scraper service"""
    try:
        redis_client = await RedisStreamClient.create(REDIS_URL)
        # Extract SKU from URL (for Amazon: last part of path)
        sku = target_url.rstrip('/').split('/')[-1]
        
        # Detect store from URL
        store = "unknown"
        if "amazon.eg" in target_url or "amazon.com" in target_url:
            store = "amazon_eg"
        elif "jumia.com.eg" in target_url:
            store = "jumia_eg"
        elif "noon.com" in target_url:
            store = "noon_eg"
        elif "elbadrgroupeg.store" in target_url:
            store = "elbadr_eg"
        elif "compumarts.com" in target_url:
            store = "compumarts_eg"
        elif "sigma-computer.com" in target_url:
            store = "sigma_eg"
        elif "geeksstoreeg.com" in target_url:
            store = "geeks_store_eg"
        elif "iravin.com" in target_url:
            store = "ravin_eg"
        elif "tie-house.com" in target_url:
            store = "tie_house_eg"
        elif "townteam.com" in target_url:
            store = "town_team_eg"
        elif "alfrensia.com" in target_url:
            store = "alfrensia_eg"
        
        target = {
            "url": target_url,
            "sku": sku,
            "store": store
        }
        await redis_client.xadd(TARGETS_STREAM, {"payload": json.dumps(target)})
        logger.info(
            "Pushed alert target to Redis",
            extra={"alert_id": alert_id, "stream": TARGETS_STREAM, "target": target},
        )
    except Exception as e:
        # Log error but don't fail the request
        logger.exception(
            "Failed to push alert target to Redis",
            extra={"alert_id": alert_id, "stream": TARGETS_STREAM, "error": str(e)},
        )

# Pydantic models
class AlertCreate(BaseModel):
    target_url: str
    target_price: float = 0.0

    @validator("target_price")
    def validate_price(cls, v):
        if v < 0:
            raise ValueError("Target price must be zero or positive")
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