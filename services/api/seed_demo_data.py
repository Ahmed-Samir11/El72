"""Idempotent demo-data seeder for the Elhaq API.

Purpose
-------
Populate the database with realistic Egyptian-market demo data so the
investor demo works end-to-end against a *running* backend (not just the
Flutter app's in-memory demo fallback).

What it seeds
-------------
1. ``price_history`` — 90 days of price points per SKU per store. This is the
   data source for Engineer B's ``GET /price-history/{sku}`` endpoint, so the
   Flutter price-history chart renders real data once that endpoint lands.
2. A demo user (``+201000000000``) so the app can log in against the API.

Design constraints
------------------
* **Idempotent** — safe to run on every startup. Existing rows are left
  untouched; missing rows are inserted.
* **Portable** — the ``price_history`` DDL uses only types that work on both
  SQLite (local demo) and PostgreSQL/TimescaleDB (production).
* **Fail-soft** — any error is raised to the caller; the caller (app startup)
  decides whether to treat it as fatal. The CLI entry point exits non-zero.

Note on ``tracked_items``
-------------------------
``tracked_items.user_id`` is declared as ``Integer`` in
``tracked_items_models.py`` while ``users.id`` is a UUID in ``models.py``.
That pre-existing inconsistency makes seeding tracked items for the demo user
unreliable on SQLite, so this seeder intentionally does **not** seed tracked
items. The Flutter dashboard falls back to its in-memory demo data for the
trackers list, which is the intended demo behaviour.
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from services.api.models import Base, User

# passlib is optional here so the seeder can run in a minimal environment
# (e.g. one that only has sqlalchemy). When it is missing, demo-user creation
# is skipped gracefully and price_history seeding still succeeds.
try:
    from passlib.context import CryptContext

    _pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
except Exception:  # pragma: no cover - optional dependency
    _pwd_context = None

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./elhaq.db")

DEMO_PHONE = "+201000000000"
DEMO_PASSWORD = "ElhaqDemo123"  # demo-only; never used in production

USD_RATE = 48.0  # EGP per USD, matches the Flutter demo data
HISTORY_DAYS = 90

# Store catalogue (id -> display name + URL base for source_url).
STORES: Dict[str, Dict[str, str]] = {
    "amazon_eg": {"name": "Amazon EG", "url_base": "https://amazon.eg/dp/"},
    "noon_eg": {"name": "Noon EG", "url_base": "https://www.noon.com/egypt-en/"},
    "jumia_eg": {"name": "Jumia EG", "url_base": "https://www.jumia.com.eg/"},
    "istyle_eg": {"name": "iStyle EG", "url_base": "https://www.istyle.com.eg/"},
}

# Per-store price factor so stores differ slightly (makes the "lowest price"
# realistic). The cheapest store wins the lowest-price badge.
STORE_PRICE_FACTOR: Dict[str, float] = {
    "amazon_eg": 1.00,
    "noon_eg": 0.98,
    "jumia_eg": 1.02,
    "istyle_eg": 1.05,
}

# Realistic Egyptian-market products. ``current_price_egp`` is the price the
# series trends *down to* (today). SKUs match the Flutter demo data so the
# chart and the list stay consistent.
DEMO_PRODUCTS: List[Dict] = [
    {
        "sku": "iphone-15-pro-max-256gb",
        "title": "Apple iPhone 15 Pro Max 256GB",
        "current_price_egp": 129999.0,
        "stores": ["amazon_eg", "noon_eg", "jumia_eg"],
    },
    {
        "sku": "playstation-5-slim-bundle",
        "title": "PlayStation 5 Slim Bundle",
        "current_price_egp": 11499.0,
        "stores": ["jumia_eg", "noon_eg"],
    },
    {
        "sku": "nvidia-rtx-4060-8gb",
        "title": "NVIDIA GeForce RTX 4060 8GB",
        "current_price_egp": 14999.0,
        "stores": ["noon_eg", "amazon_eg", "jumia_eg", "istyle_eg"],
    },
]

# Portable DDL: works on SQLite and PostgreSQL/TimescaleDB.
_PRICE_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS price_history (
    time TIMESTAMP NOT NULL,
    sku TEXT NOT NULL,
    store_id TEXT NOT NULL,
    price_usd NUMERIC NOT NULL,
    price_local NUMERIC NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    in_stock BOOLEAN NOT NULL DEFAULT 1,
    source_url TEXT,
    PRIMARY KEY (time, sku, store_id)
)
"""


# --------------------------------------------------------------------------- #
# Price series generation
# --------------------------------------------------------------------------- #
def _generate_series(
    sku: str,
    store_id: str,
    current_price_egp: float,
    days: int = HISTORY_DAYS,
) -> List[Tuple[datetime, float]]:
    """Return ``[(time, price_egp), ...]`` for ``days`` days ending today.

    Deterministic per (sku, store) so re-runs are stable. The series starts
    ~12% above the current price and trends down to it, with small noise and
    an occasional dip, mirroring the Flutter demo chart shape.
    """
    rng = random.Random(f"{sku}:{store_id}")
    start_price = current_price_egp * 1.12
    now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    points: List[Tuple[datetime, float]] = []
    for i in range(days):
        t = now - timedelta(days=days - 1 - i)
        progress = i / (days - 1)
        trend = start_price + (current_price_egp - start_price) * progress
        noise = rng.uniform(-0.02, 0.02) * current_price_egp
        dip = -0.05 * current_price_egp if (i % 23 == 10) else 0.0
        price = max(1.0, round(trend + noise + dip, 2))
        points.append((t, price))

    # Pin the final point to exactly the current price for a clean "today".
    points[-1] = (now, round(current_price_egp, 2))
    return points


# --------------------------------------------------------------------------- #
# Seeding steps
# --------------------------------------------------------------------------- #
def _ensure_price_history_table(engine: Engine) -> None:
    """Create ``price_history`` if it does not already exist (portable)."""
    with engine.begin() as conn:
        conn.execute(text(_PRICE_HISTORY_DDL))


def _seed_price_history(session: Session) -> int:
    """Insert 90 days of price history per SKU/store. Returns rows inserted."""
    inserted = 0
    for product in DEMO_PRODUCTS:
        sku = product["sku"]
        # Idempotency: skip SKUs that already have history.
        existing = session.execute(
            text("SELECT COUNT(*) FROM price_history WHERE sku = :sku"),
            {"sku": sku},
        ).scalar()
        if existing:
            continue

        for store_id in product["stores"]:
            factor = STORE_PRICE_FACTOR.get(store_id, 1.0)
            store_current = product["current_price_egp"] * factor
            series = _generate_series(sku, store_id, store_current)
            url_base = STORES.get(store_id, {}).get("url_base", "")
            source_url = f"{url_base}{sku}"

            rows = [
                {
                    "time": t,
                    "sku": sku,
                    "store_id": store_id,
                    "price_usd": round(price / USD_RATE, 4),
                    "price_local": round(price, 2),
                    "currency": "EGP",
                    "in_stock": True,
                    "source_url": source_url,
                }
                for (t, price) in series
            ]
            session.execute(
                text(
                    "INSERT INTO price_history "
                    "(time, sku, store_id, price_usd, price_local, currency, "
                    " in_stock, source_url) "
                    "VALUES (:time, :sku, :store_id, :price_usd, :price_local, "
                    " :currency, :in_stock, :source_url)"
                ),
                rows,
            )
            inserted += len(rows)
    return inserted


def _seed_demo_user(session: Session) -> bool:
    """Create the demo user if it does not already exist. Returns True if new.

    Returns False (no-op) when passlib is unavailable, so the seeder can still
    run in a minimal environment.
    """
    if _pwd_context is None:
        return False

    existing = session.query(User).filter(User.phone == DEMO_PHONE).first()
    if existing is not None:
        return False

    import secrets

    demo_user = User(
        phone=DEMO_PHONE,
        password_hash=_pwd_context.hash(DEMO_PASSWORD),
        salt=secrets.token_hex(16),
        tier="free",
    )
    session.add(demo_user)
    return True


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def run_seed(engine: Optional[Engine] = None) -> Dict:
    """Run the full idempotent seed. Returns a summary dict.

    Parameters
    ----------
    engine:
        Optional SQLAlchemy engine to reuse (e.g. the app's engine). If
        omitted, one is created from ``DATABASE_URL``.
    """
    own_engine = engine is None
    if engine is None:
        engine = create_engine(DATABASE_URL)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: Session = SessionLocal()
    summary: Dict = {"price_history_rows": 0, "demo_user_created": False}

    try:
        # Ensure ORM-managed tables (users, alerts) exist so the demo user can
        # be created. Idempotent.
        Base.metadata.create_all(bind=engine)
        _ensure_price_history_table(engine)
        session.begin()
        summary["price_history_rows"] = _seed_price_history(session)
        summary["demo_user_created"] = _seed_demo_user(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        if own_engine:
            engine.dispose()

    return summary


if __name__ == "__main__":
    result = run_seed()
    print(f"🌱 Demo seed complete: {result}")
    print(f"   Demo login: {DEMO_PHONE} / {DEMO_PASSWORD}")
