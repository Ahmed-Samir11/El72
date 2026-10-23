"""Backfill prices/images for existing trackers using the fixed fetcher."""
import sys
sys.path.insert(0, "e:/repos/El72")

from datetime import datetime
from sqlalchemy import text

from services.api.dependencies import SessionLocal
from services.api.price_fetcher import fetch_price_sync, _to_usd
from services.api.tracked_items_models import CurrentPrice, LowestPrice


def backfill(tracked_item_id, store_id, url, canonical_id):
    print(f"\n=== tracker {tracked_item_id} ({store_id}) ===")
    fetched = fetch_price_sync(url)
    if fetched is None:
        print("  no price fetched (URL dead / blocked / no price found)")
        return
    print(f"  fetched: {fetched.price_local} {fetched.currency} | title={fetched.title!r}")
    print(f"  image: {fetched.image_url!r}")

    db = SessionLocal()
    try:
        price_usd = _to_usd(fetched.price_local, fetched.currency)
        now = datetime.utcnow()

        existing = db.query(CurrentPrice).filter(
            CurrentPrice.tracked_item_id == tracked_item_id,
            CurrentPrice.store_id == store_id,
        ).first()
        if existing:
            existing.price_usd = price_usd
            existing.price_local = fetched.price_local
            existing.currency = fetched.currency
            existing.in_stock = fetched.in_stock
            existing.last_updated = now
        else:
            db.add(CurrentPrice(
                tracked_item_id=tracked_item_id, store_id=store_id,
                price_usd=price_usd, price_local=fetched.price_local,
                currency=fetched.currency, in_stock=fetched.in_stock,
                last_updated=now,
            ))

        low = db.query(LowestPrice).filter(
            LowestPrice.tracked_item_id == tracked_item_id
        ).first()
        if low:
            low.store_id = store_id
            low.price_usd = price_usd
            low.price_local = fetched.price_local
            low.currency = fetched.currency
            low.url = url
            low.last_updated = now
        else:
            db.add(LowestPrice(
                tracked_item_id=tracked_item_id, store_id=store_id,
                price_usd=price_usd, price_local=fetched.price_local,
                currency=fetched.currency, url=url, last_updated=now,
            ))

        try:
            db.execute(
                text(
                    "INSERT INTO price_history "
                    "(time, sku, store_id, price_usd, price_local, currency, in_stock, source_url, image_url) "
                    "VALUES (:t, :sku, :store, :usd, :local, :cur, :stock, :url, :img)"
                ),
                {
                    "t": now, "sku": canonical_id, "store": store_id,
                    "usd": price_usd, "local": fetched.price_local,
                    "cur": fetched.currency, "stock": 1 if fetched.in_stock else 0,
                    "url": url, "img": fetched.image_url,
                },
            )
        except Exception as e:
            print("  (history insert skipped:", e, ")")
            db.rollback()

        db.commit()
        print("  persisted OK")
    finally:
        db.close()


# (tracked_item_id, store_id, url, canonical_id)
TRACKERS = [
    (1, "alfrensia_eg",
     "https://alfrensia.com/en/product/asus-a23-micro-atx-support-hatsune-miku-white-edition-micro-tower-case/",
     "alfrensia_eg:asus-a23-micro-atx-support-hatsune-miku-white-edition-micro-tower-case"),
    (2, "alfrensia_eg",
     "https://alfrensia.com/en/product/asus-tuf-gaming-f15-rtx-4060-laptop/",
     "alfrensia_eg:asus-tuf-gaming-f15-rtx-4060-laptop"),
    (3, "compumarts_eg",
     "https://www.compumarts.com/collections/monitors/products/lenovo-legion-r27qe-gaming-monitor-27-inch-2560x1440-displayhdr-400-ips-panel-technology-200hz-refresh-rate-0-5ms-response-time",
     "compumarts_eg:lenovo-legion-r27qe-gaming-monitor-27-inch-2560x1440-displayhdr-400-ips-panel-technology-200hz-refresh-rate-0-5ms-response-time"),
]

for tid, store, url, canon in TRACKERS:
    backfill(tid, store, url, canon)

print("\nDone.")
