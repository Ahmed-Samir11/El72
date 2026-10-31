import asyncio
import json
import logging
import os
import time
from contextlib import suppress

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware

from services.api import usage_limits
from services.api.affiliate import missing_affiliate_tags
from services.api.alert_events_consumer import consume_loop
from services.api.card_payment_models import CardPayment  # noqa: F401
from services.api.dependencies import get_current_user, get_db
from services.api.manual_payment_models import ManualPayment  # noqa: F401
from services.api.models import Alert, Base, User
from services.api.monitoring.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    metrics_response,
)
from services.api.routers import affiliate as affiliate_router
from services.api.routers import alerts as alerts_router
from services.api.routers import auth, public_api
from services.api.routers import credits as credits_router
from services.api.routers import payment as payment_router
from services.api.routers import subscription as subscription_router
from services.api.tracked_items_api import router as tracked_items_router
from services.api.tracked_items_models import Base as TrackedBase
from services.common.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)

# Configuration. The JWT signing key is resolved in services.api.dependencies
# (no default, so a missing SECRET_KEY fails at startup rather than silently
# signing tokens with a well-known key).
ACCESS_TOKEN_EXPIRE_MINUTES = 30

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./elhaq.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TARGETS_STREAM = "stream:targets"

# The alert-events consumer (plans/p2 MS1) runs in-process: stream:alerts ->
# alert_events, so a price event is still present the next time the app opens.
# Enabled by default because an API without it serves an Alerts tab that stays
# silently empty; set ALERT_EVENTS_CONSUMER=false only when Redis is deliberately
# absent, where el72_alert_events_consumer_up reads 0 instead of lying quietly.
ALERT_EVENTS_CONSUMER_ENABLED = os.getenv("ALERT_EVENTS_CONSUMER", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)
TrackedBase.metadata.create_all(bind=engine)

# In-place column migration for databases created before the new columns
# (last_fetch_status/last_fetch_error, image_url) existed. create_all adds
# missing tables but not columns, so upgraded DBs need this. This is
# fail-HARD on purpose: the tracked-items endpoints query these columns, so
# starting without them would surface as confusing 500s later — a boot
# failure is the honest signal. (create_tables is import-safe: it creates
# no engine at import time; concurrent startups are handled by
# IF NOT EXISTS / duplicate-column tolerance inside ensure_columns.)
from services.api.create_tables import ensure_columns  # noqa: E402

ensure_columns(engine)

from sqlalchemy.exc import IntegrityError  # noqa: E402

from services.api.admin_models import Admin  # noqa: E402
from services.api.dependencies import get_password_hash  # noqa: E402


def bootstrap_admin() -> None:
    """Create the first admin credential from env vars if none exists.

    Admins are a separate credential (not a user tier); after the first
    bootstrap, new admins must be provisioned out-of-band. Idempotent and
    concurrency-safe: if two instances race to create the first admin, the
    loser hits the username UNIQUE constraint and continues harmlessly.
    """
    admin_username = os.getenv("ADMIN_USERNAME")
    admin_password = os.getenv("ADMIN_PASSWORD")

    session = SessionLocal()
    try:
        if session.query(Admin).count() == 0 and admin_username and admin_password:
            session.add(
                Admin(
                    username=admin_username,
                    password_hash=get_password_hash(admin_password),
                )
            )
            try:
                session.commit()
                logger.info("Bootstrapped first admin credential")
            except IntegrityError:
                # Lost the race to a concurrent startup; the other instance
                # already created the admin.
                session.rollback()
        else:
            # No existing admin and no credentials configured: the admin
            # panel is unavailable. Surface this to operators at startup.
            if session.query(Admin).count() == 0:
                logger.warning(
                    "No admin credentials configured (ADMIN_USERNAME / "
                    "ADMIN_PASSWORD unset) and no admin exists; the admin "
                    "payment endpoints will be unusable."
                )
    finally:
        session.close()


# Prometheus Class
class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        start_time = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start_time

        endpoint = request.url.path
        method = request.method
        status = str(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            endpoint=endpoint,
            status=status,
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method,
            endpoint=endpoint,
        ).observe(duration)

        return response


# Trusted proxies: only a direct peer in this env-configured set may
# supply X-Forwarded-For for the rate-limit key. Otherwise the direct socket
# address is used, so a client cannot spoof the header to bypass per-IP
# limits.
TRUSTED_PROXIES = {
    p.strip() for p in os.getenv("TRUSTED_PROXIES", "").split(",") if p.strip()
}

# CORS origins: explicit allowlist. In production ALLOWED_ORIGINS must be
# set to the real origin(s); dev fallback keeps the localhost list and never
# allows "*" with credentials.
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
] or ["http://localhost:8080", "http://127.0.0.1:8080"]


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting.

    X-Forwarded-For is honored only when the direct peer is a configured
    trusted proxy; otherwise the direct socket address is used.
    """
    # request.client is a (host, port) tuple; index 0 is the address.
    peer = request.client[0] if request.client else None
    if peer in TRUSTED_PROXIES:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
    return peer or "unknown"


app = FastAPI(title="Elhaq API")
limiter = Limiter(key_func=_client_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    PrometheusMiddleware,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers


def mount_routers(target: FastAPI, *, payment_surface: bool) -> None:
    """Mount the API surface on ``target``.

    Kept as a function rather than module-level calls so both postures are
    testable without re-importing this module (which would rebuild its
    engine) mid-session — and so the payment gate is one auditable decision
    instead of six lines a later edit can silently un-gate.

    ``payment_surface`` is decided by the caller: a release backend (the
    shipped default — CREDITS_ENFORCEMENT=fair_use with PAYMENTS_ENABLED unset)
    registers no Paymob route at all, which is how the store listing can honestly
    make no payment claim, keeps the financial-transaction surface unattackable,
    and asks no payment decision of a user who does not yet trust the product.
    PAYMENTS_ENABLED=true — or the legacy CREDITS_ENFORCEMENT=on — mounts it
    again: the rails are flagged out of the release, not deleted (plans/p3).
    """
    target.include_router(auth.router, prefix="/auth", tags=["Auth"])

    # Public demo endpoints (no auth) consumed by the landing page and Flutter app:
    # /stats, /deals/live, /price-history/{sku}, /pricing.
    target.include_router(public_api.router)

    # Credit balance endpoints (auth required): /credits/balance, /credits/transactions.
    # Ledger reads only — a tracker is never gated by this number in the shipped
    # model, but the surface stays for the legacy mode and a future premium tier.
    target.include_router(credits_router.router)

    # Fair-use state for the free tracker: GET /usage/limits returns
    # {active_trackers, cap, created_last, retry_after_seconds, enforcement}. It
    # replaces "credits remaining" in the client's Profile tab and carries the
    # per-user tracker count P4's engagement rollups need (plans/p3 WS1/WS4).
    target.include_router(usage_limits.router)

    # Affiliate click tracking and safe merchant redirects.
    target.include_router(affiliate_router.router)

    # Alert surface: GET /alerts/recent + POST /alerts/{id}/open (plans/p2 MS1).
    # Kept in its own router so the two meanings of "alert" stay separate: this
    # one reads alert EVENTS, while main.py's POST /alerts creates a tracker.
    target.include_router(alerts_router.router)

    # Tracked-item lifecycle. Creation is bounded by the fair-use cap and the
    # creation rate window (see services/api/usage_limits.py).
    target.include_router(tracked_items_router)

    if payment_surface:
        # Manual payment flow (bridge to Paymob) — this router also carries the
        # admin payment surface (/admin/login, /admin/audit-log), so a release
        # build with payment_surface=False has no /admin route either: there is
        # no payment-administration endpoint to reach.
        target.include_router(payment_router.router)

        # Recurring subscriptions (Paymob subscriptions, Feature 7).
        target.include_router(subscription_router.router)


# Evaluated once at import, so the mount, the startup log and any later check
# report one decision rather than re-reading an environment that may have moved
# under the process.
ENFORCEMENT_AT_IMPORT = usage_limits.enforcement_mode()
MAX_TRACKERS_AT_IMPORT = usage_limits.max_trackers()
PAYMENT_SURFACE_ENABLED = usage_limits.payments_surface_enabled()
mount_routers(app, payment_surface=PAYMENT_SURFACE_ENABLED)

# Demo mode: seed realistic demo data on startup (idempotent).
# Toggle with DEMO_MODE=True (default) for the investor demo.
DEMO_MODE = os.getenv("DEMO_MODE", "False").lower() in ("1", "true", "yes", "on")


@app.on_event("startup")
def _report_fair_use_posture() -> None:
    """Log the enforcement mode and whether any payment surface is mounted.

    The release posture must be auditable from the running process, not only
    from the compose file: "this backend sells no trackers, and bounds tracking
    by fair use" is a claim an operator can check against the store listing.
    The values logged are the ones that decided the mount, so the log cannot
    disagree with the routes that exist.
    """
    fair_use = ENFORCEMENT_AT_IMPORT == usage_limits.FAIR_USE
    logger.info(
        "Tracker creation enforcement posture",
        extra={
            "credits_enforcement": ENFORCEMENT_AT_IMPORT,
            "fair_use_max_trackers": (MAX_TRACKERS_AT_IMPORT if fair_use else None),
            "creation_min_interval_seconds": (
                usage_limits.MIN_CREATION_INTERVAL_SECONDS if fair_use else None
            ),
            "payment_routes_mounted": PAYMENT_SURFACE_ENABLED,
        },
    )


@app.on_event("startup")
def _warn_on_unconfigured_affiliate_tags() -> None:
    """An unconfigured *_AFFILIATE_TAG must be loud in production (plan p1, C8).

    Without a tag, build_affiliate_url passes the merchant URL through:
    every click is still logged but earns nothing. That difference — "we
    measured zero" vs "we forgot to configure" — must be an operator-visible
    startup WARNING naming the store, not a silent no-op. Outside
    APP_ENV=production, empty tags are the documented dev default and stay
    quiet (GET /affiliate/config reports presence in every mode).
    """
    if os.getenv("APP_ENV", "").strip().lower() != "production":
        return
    for store_id, env_var in missing_affiliate_tags():
        logger.warning(
            "Affiliate tag not configured: clicks for this store are "
            "attributed but earn no revenue",
            extra={"store_id": store_id, "env_var": env_var},
        )


@app.on_event("startup")
def _seed_demo_data_on_startup() -> None:
    bootstrap_admin()
    if not DEMO_MODE:
        return
    try:
        from services.api.seed_demo_data import run_seed

        summary = run_seed(engine=engine)
        logger.info("Demo data seeded on startup", extra={"summary": summary})
    except Exception:
        logger.exception("Demo seed failed; API startup is stopping")
        raise


@app.on_event("startup")
async def _start_alert_events_consumer() -> None:
    """Start the in-process stream:alerts -> alert_events consumer (plans/p2 MS1).

    The task never blocks startup: Redis is connected to lazily inside the
    consumer loop, so an outage reads as ``el72_alert_events_consumer_up 0`` plus
    ``el72_alert_events_read_errors_total`` rather than as an API that will not
    boot. Disabled only by explicit configuration, and then the log says so, so
    "the Alerts tab is empty" can be traced to "the consumer is off".
    """
    if not ALERT_EVENTS_CONSUMER_ENABLED:
        logger.info(
            "Alert events consumer disabled (ALERT_EVENTS_CONSUMER=false): "
            "stream:alerts will not be persisted, so the Alerts feed stays empty"
        )
        return
    existing = getattr(app.state, "alert_events_task", None)
    if existing is not None and not existing.done():
        # A second startup in the same process (test harness, hot reload) must
        # not replace the running consumer: two tasks, one stream group and
        # one gauge, would make "the consumer is up" mean "one of them is".
        logger.info("Alert events consumer already running; not starting a second")
        return
    app.state.alert_events_task = asyncio.create_task(consume_loop(SessionLocal))


@app.on_event("shutdown")
async def _stop_alert_events_consumer() -> None:
    """Cancel the consumer task so a reload cannot leave a second consumer behind."""
    task = getattr(app.state, "alert_events_task", None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@app.get("/metrics", include_in_schema=False)
async def metrics():
    content, media_type = metrics_response()

    return Response(
        content=content,
        media_type=media_type,
    )


# Call for API health
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


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

        target = {"url": target_url, "sku": sku, "store": store}
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
def create_alert(
    alert: AlertCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Validate URL (basic)
    if not alert.target_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    # Create alert
    db_alert = Alert(
        user_id=current_user.id,
        target_url=alert.target_url,
        target_price=alert.target_price,
        active_status=True,
    )
    db.add(db_alert)
    db.commit()
    db.refresh(db_alert)

    # Push to Redis stream in background
    background_tasks.add_task(push_to_stream, alert.target_url, db_alert.id)

    return {"id": db_alert.id, "message": "Alert created and target pushed to scraper"}
