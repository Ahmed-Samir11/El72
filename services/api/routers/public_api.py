"""Public, no-auth API endpoints that power the investor demo.

These four endpoints are consumed by the landing page (``frontend/``) and the
Flutter app (``flutter-app/``):

* ``GET /stats``               — platform-wide stats (trackers, deals, savings)
* ``GET /deals/live``          — live deal discovery feed
* ``GET /price-history/{sku}`` — price history for the chart screen
* ``GET /pricing``             — tiered pricing

All data is derived from the seeded ``price_history`` table (populated by
``services/api/seed_demo_data.py`` and Engineer C's ``seed_data.py``), so the
demo is alive against a running backend rather than relying on client-side
fallbacks.

Design notes
------------
* **Public (no auth)** — the landing page calls these unauthenticated; the
  Flutter app's auth interceptor simply adds a token that these endpoints
  ignore.
* **Fail-soft** — if ``price_history`` does not exist yet (fresh database),
  endpoints return empty results instead of 500ing.
* **DRY** — the plan listed these as three separate router files; they share
  one data source (``price_history``) and one query helper, so they are
  consolidated here to avoid duplicating the access layer.
"""

import os
from typing import Dict, List
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.api.dependencies import get_db

router = APIRouter(tags=["public"])
limiter = Limiter(key_func=get_remote_address)

# Store display names (id -> human label). Mirrors the seeder catalogue.
STORE_NAMES: Dict[str, str] = {
    "amazon_eg": "Amazon EG",
    "noon_eg": "Noon EG",
    "jumia_eg": "Jumia EG",
    "istyle_eg": "iStyle EG",
    "tie_house_eg": "Tie House",
    "town_team_eg": "Town Team",
    "elbadr_eg": "El Badr Group",
    "compumarts_eg": "CompuMarts",
    "geeks_store_eg": "Geeks Store",
    "ravin_eg": "Ravin",
    "alfrensia_eg": "Alfrensia",
}

PRODUCT_TITLES: Dict[str, str] = {
    "rtx-5060-el-badr": "Gigabyte RTX 5060 WINDFORCE MAX OC 8GB",
    "rtx-5060-compumarts": "ZOTAC RTX 5060 Twin Edge 8GB",
    "asus-rog-hatsune-miku-xg27acmeg-g": "ASUS ROG Strix Hatsune Miku 27 XG27ACMEG-G",
    "ravin-white-fruit-print-tee-r219636": "White Oversized Fresh and Tasty Graphic Tee",
}


def _humanize_sku(sku: str) -> str:
    """Turn a canonical SKU into a readable product title."""
    words = sku.replace("-", " ").replace("_", " ").split()
    return " ".join(w[:1].upper() + w[1:] for w in words).strip() or sku


def _to_iso(t) -> str:
    """Normalize a stored timestamp to a clean ISO-8601 string (``T``-separated).

    SQLite returns TIMESTAMP columns as strings (``"2026-06-16 00:00:00.000000"``);
    this also handles a real ``datetime`` for portability.
    """
    if hasattr(t, "isoformat"):
        return t.replace(microsecond=0).isoformat()
    s = str(t).strip().replace(" ", "T", 1)
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _price_history_rows(session: Session, sku: str | None = None) -> List[dict]:
    """Return ``price_history`` rows (optionally for one sku) as dicts.

    Fails soft: returns ``[]`` if the table does not exist yet.
    """
    if sku is None:
        sql = (
            "SELECT time, sku, store_id, price_usd, price_local, currency, "
            "in_stock, source_url, image_url FROM price_history"
        )
        params: dict = {}
    else:
        sql = (
            "SELECT time, sku, store_id, price_usd, price_local, currency, "
            "in_stock, source_url, image_url FROM price_history WHERE sku = :sku"
        )
        params = {"sku": sku}
    try:
        result = session.execute(text(sql), params)
    except SQLAlchemyError:
        session.rollback()
        legacy_sql = sql.replace(", image_url", "")
        try:
            result = session.execute(text(legacy_sql), params)
        except SQLAlchemyError:
            return []
    return [dict(row._mapping) for row in result]


def _first_last_per_sku(rows: List[dict]) -> Dict[str, dict]:
    """For each sku, the lowest-price row on the earliest and latest day.

    Returns ``{sku: {"first": {...}, "last": {...}}}`` where each entry has
    ``_t`` (ISO time), ``price_local`` (float) and ``store_id``.
    """
    per_sku: Dict[str, dict] = {}
    for r in rows:
        sku = r["sku"]
        t = _to_iso(r["time"])
        price = float(r["price_local"])
        e = per_sku.setdefault(sku, {"first": None, "last": None})
        if e["first"] is None or t < e["first"]["_t"]:
            e["first"] = {
                "_t": t,
                "price_local": price,
                "store_id": r["store_id"],
                "source_url": r.get("source_url"),
                "image_url": r.get("image_url"),
            }
        elif t == e["first"]["_t"] and price < e["first"]["price_local"]:
            e["first"] = {
                "_t": t,
                "price_local": price,
                "store_id": r["store_id"],
                "source_url": r.get("source_url"),
                "image_url": r.get("image_url"),
            }
        if e["last"] is None or t > e["last"]["_t"]:
            e["last"] = {
                "_t": t,
                "price_local": price,
                "store_id": r["store_id"],
                "source_url": r.get("source_url"),
                "image_url": r.get("image_url"),
            }
        elif t == e["last"]["_t"] and price < e["last"]["price_local"]:
            e["last"] = {
                "_t": t,
                "price_local": price,
                "store_id": r["store_id"],
                "source_url": r.get("source_url"),
                "image_url": r.get("image_url"),
            }
    return per_sku


@router.get("/price-history/{sku}")
@limiter.limit("60/minute")
def get_price_history(
    request: Request, sku: str, db: Session = Depends(get_db)
) -> List[dict]:
    """Best (lowest) price across stores per day for a product.

    Returns one clean series (a single point per day) so the Flutter chart
    renders one line: the lowest price the product has been at, over time.
    """
    rows = _price_history_rows(db, sku)
    if not rows:
        return []

    by_day: Dict[str, dict] = {}
    for r in rows:
        t = _to_iso(r["time"])
        price = float(r["price_local"])
        cur = by_day.get(t)
        if cur is None or price < cur["price_local"]:
            by_day[t] = {
                "time": t,
                "price_local": round(price, 2),
                "price_usd": round(float(r["price_usd"]), 2),
                "in_stock": bool(r["in_stock"]),
            }
    return [by_day[t] for t in sorted(by_day)]


@router.get("/deals/live")
@limiter.limit("60/minute")
def get_live_deals(request: Request, db: Session = Depends(get_db)) -> List[dict]:
    """Live deal discovery feed.

    A "deal" is a product whose current (latest-day) lowest price is below its
    90-day-high (earliest-day) lowest price. Ranked by discount depth.
    """
    rows = _price_history_rows(db)
    if not rows:
        return []

    deals: List[dict] = []
    for sku, e in _first_last_per_sku(rows).items():
        original = e["first"]["price_local"]
        current = e["last"]["price_local"]
        if original <= 0 or current >= original:
            continue  # no genuine drop
        discount = (original - current) / original * 100
        source_url = e["last"].get("source_url") or ""
        redirect_url = source_url
        if source_url:
            base_url = os.getenv("PUBLIC_API_BASE_URL", "http://localhost:8000").rstrip("/")
            redirect_url = (
                f"{base_url}/affiliate/redirect?"
                f"{urlencode({'target_url': source_url, 'sku': sku, 'deal_id': sku})}"
            )
        deals.append(
            {
                "id": sku,
                "title": PRODUCT_TITLES.get(sku, _humanize_sku(sku)),
                "store_name": STORE_NAMES.get(e["last"]["store_id"], e["last"]["store_id"]),
                "image_url": e["last"].get("image_url") or "",
                "price": round(current, 2),
                "original_price": round(original, 2),
                "discount_percentage": round(discount, 1),
                "url": redirect_url,
                "source_url": source_url,
            }
        )

    deals.sort(key=lambda d: d["discount_percentage"], reverse=True)
    return deals


@router.get("/stats")
@limiter.limit("60/minute")
def get_stats(request: Request, db: Session = Depends(get_db)) -> dict:
    """Platform-wide stats derived from the seeded price history.

    Returns both key sets so the two consumers are satisfied:
    * Flutter: ``total_trackers`` / ``deals_today`` / ``total_savings``
    * Landing: ``total_trackers`` / ``deals_found_today`` /
      ``total_savings_egp`` / ``stores_monitored``
    """
    rows = _price_history_rows(db)
    if not rows:
        return {
            "total_trackers": 0,
            "deals_today": 0,
            "total_savings": 0.0,
            "deals_found_today": 0,
            "total_savings_egp": 0.0,
            "stores_monitored": 0,
        }

    per_sku = _first_last_per_sku(rows)
    total_savings = 0.0
    deals_today = 0
    for e in per_sku.values():
        original = e["first"]["price_local"]
        current = e["last"]["price_local"]
        total_savings += max(0.0, original - current)
        if current < original:
            deals_today += 1

    return {
        "total_trackers": len(per_sku),
        "deals_today": deals_today,
        "total_savings": round(total_savings, 2),
        "deals_found_today": deals_today,
        "total_savings_egp": round(total_savings, 2),
        "stores_monitored": len({r["store_id"] for r in rows}),
    }


@router.get("/pricing")
@limiter.limit("60/minute")
def get_pricing(request: Request) -> dict:
    """Tiered pricing (matches the landing page pricing section)."""
    return {
        "currency": "EGP",
        "tiers": [
            {
                "id": "free",
                "name": "Free",
                "price_egp": 0,
                "credits": 3,
                "max_trackers": 3,
                "features": [
                    "3 active trackers",
                    "WhatsApp deal alerts",
                    "Price history charts",
                ],
            },
            {
                "id": "standard",
                "name": "Standard",
                "price_egp": 30,
                "credits": 10,
                "max_trackers": -1,
                "features": [
                    "10 active trackers",
                    "Cross-store best-price",
                    "Priority deal queue",
                ],
            },
            {
                "id": "premium",
                "name": "Premium",
                "price_egp": 90,
                "credits": 30,
                "max_trackers": -1,  # unlimited
                "features": [
                    "Unlimited trackers",
                    "Category deal feed",
                    "Early access features",
                ],
            },
        ],
    }
