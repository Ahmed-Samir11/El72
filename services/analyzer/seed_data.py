"""Deterministic Egyptian e-commerce demo dataset generator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Sequence

import asyncpg

DEMO_PREFIX = "demo-el72-"
DEFAULT_SEED = 7242
DEFAULT_START_DATE = date(2025, 9, 1)
DEFAULT_DAYS = 90
EGP_TO_USD = Decimal("0.032")
STORES = ("amazon_eg", "noon", "jumia_eg", "btech_eg")
STORE_MULTIPLIERS = {
    "amazon_eg": Decimal("1.00"),
    "noon": Decimal("1.08"),
    "jumia_eg": Decimal("0.94"),
    "btech_eg": Decimal("1.03"),
}


@dataclass(frozen=True)
class ProductConfig:
    product_id: str
    name: str
    category: str
    baseline_egp: Decimal
    volatility: Decimal
    trend: Decimal = Decimal("0")
    scenario: str = "normal"


@dataclass(frozen=True)
class PriceObservation:
    product_id: str
    sku: str
    store_id: str
    timestamp: datetime
    price_local: Decimal
    price_usd: Decimal
    in_stock: bool
    source_url: str
    scenario: str
    advertised_reference_price: Decimal | None = None


@dataclass(frozen=True)
class DemoDataset:
    products: tuple[ProductConfig, ...]
    observations: tuple[PriceObservation, ...]
    start_date: date
    end_date: date
    seed: int


PRODUCTS: tuple[ProductConfig, ...] = (
    ProductConfig("demo-el72-genuine-laptop", "Lenovo Legion 5", "laptops", Decimal("48000"), Decimal("0.012"), scenario="genuine_deal"),
    ProductConfig("demo-el72-fake-phone", "Samsung Galaxy A55", "smartphones", Decimal("18500"), Decimal("0.008"), scenario="fake_discount"),
    ProductConfig("demo-el72-cross-store-tv", "TCL 55-inch QLED TV", "tvs", Decimal("26500"), Decimal("0.010"), scenario="cross_store"),
    ProductConfig("demo-el72-ramadan-airfryer", "Philips Airfryer XL", "home_appliances", Decimal("9200"), Decimal("0.014"), scenario="seasonal"),
    ProductConfig("demo-el72-volatile-gpu", "RTX 4060 Gaming GPU", "gaming", Decimal("28500"), Decimal("0.070"), scenario="volatile"),
    ProductConfig("demo-el72-stable-headphones", "Anker Soundcore Q45", "headphones", Decimal("6800"), Decimal("0.0015"), scenario="stable"),
    ProductConfig("demo-el72-inflation-washing", "Beko 9kg Washing Machine", "home_appliances", Decimal("22500"), Decimal("0.009"), Decimal("0.0018"), "inflation"),
    ProductConfig("demo-el72-back-school-tablet", "Xiaomi Pad 6", "accessories", Decimal("16200"), Decimal("0.011"), scenario="back_to_school"),
    ProductConfig("demo-el72-genuine-phone", "Apple iPhone 15", "smartphones", Decimal("52000"), Decimal("0.009"), scenario="price_recovery"),
    ProductConfig("demo-el72-gaming-monitor", "AOC 27G2 Monitor", "gaming", Decimal("11800"), Decimal("0.018"), scenario="white_friday"),
    ProductConfig("demo-el72-fashion-watch", "Huawei Watch GT 4", "fashion", Decimal("10500"), Decimal("0.013"), scenario="normal"),
    ProductConfig("demo-el72-accessory-mouse", "Logitech MX Master 3S", "accessories", Decimal("5200"), Decimal("0.016"), scenario="normal"),
)


def _round_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _event_factor(product: ProductConfig, day_index: int, days: int) -> Decimal:
    factor = Decimal("1")
    if product.scenario in {"seasonal", "back_to_school"} and 8 <= day_index <= 21:
        factor *= Decimal("0.91")
    if product.scenario in {"seasonal", "white_friday"} and 78 <= day_index <= min(days - 1, 88):
        factor *= Decimal("0.86")
    if product.scenario == "genuine_deal" and 58 <= day_index <= 68:
        factor *= Decimal("0.76")
    if product.scenario == "price_recovery":
        if 48 <= day_index <= 58:
            factor *= Decimal("0.80")
        elif day_index > 58:
            factor *= Decimal("0.80") + Decimal("0.20") * Decimal(day_index - 58) / Decimal("31")
    if product.scenario == "fake_discount":
        if 48 <= day_index <= 54:
            factor *= Decimal("1.20")
        elif 55 <= day_index <= 64:
            factor *= Decimal("0.96")
    return factor


def _is_in_stock(product: ProductConfig, day_index: int, store_index: int) -> bool:
    if product.scenario == "volatile" and (day_index + store_index) % 37 == 0:
        return False
    return (day_index + store_index) % 53 != 0


def generate_dataset(
    seed: int = DEFAULT_SEED,
    start_date: date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS,
    products: Sequence[ProductConfig] = PRODUCTS,
) -> DemoDataset:
    if days < 1:
        raise ValueError("days must be positive")
    rng = random.Random(seed)
    observations: list[PriceObservation] = []
    for product in products:
        for store_index, store_id in enumerate(STORES):
            sku = f"{product.product_id}-{store_id}"
            source_url = f"https://demo.{store_id}.example/products/{sku}"
            store_multiplier = STORE_MULTIPLIERS[store_id]
            for day_index in range(days):
                timestamp = datetime.combine(start_date + timedelta(days=day_index), time(12), tzinfo=timezone.utc)
                noise = Decimal(str(rng.gauss(0, float(product.volatility))))
                trend = product.trend * Decimal(day_index)
                factor = Decimal("1") + trend + noise
                factor *= _event_factor(product, day_index, days)
                price = _round_price(product.baseline_egp * store_multiplier * factor)
                price = max(price, Decimal("1.00"))
                reference = None
                if product.scenario == "fake_discount" and 55 <= day_index <= 64:
                    reference = _round_price(product.baseline_egp * store_multiplier * Decimal("1.20"))
                observations.append(
                    PriceObservation(
                        product_id=product.product_id,
                        sku=sku,
                        store_id=store_id,
                        timestamp=timestamp,
                        price_local=price,
                        price_usd=_round_price(price * EGP_TO_USD),
                        in_stock=_is_in_stock(product, day_index, store_index),
                        source_url=source_url,
                        scenario=product.scenario,
                        advertised_reference_price=reference,
                    )
                )
    return DemoDataset(
        products=tuple(products),
        observations=tuple(observations),
        start_date=start_date,
        end_date=start_date + timedelta(days=days - 1),
        seed=seed,
    )


def _demo_user_phone(seed: int, index: int) -> str:
    return f"+201000{seed:04d}{index:03d}"


def _demo_product_ids(dataset: DemoDataset) -> tuple[str, ...]:
    return tuple(product.product_id for product in dataset.products)


async def _reset_core(conn: asyncpg.Connection, dataset: DemoDataset) -> None:
    product_ids = _demo_product_ids(dataset)
    await conn.execute("DELETE FROM tracked_items WHERE canonical_product_id = ANY($1::text[])", product_ids)
    await conn.execute("DELETE FROM users WHERE phone LIKE $1", f"+201000{dataset.seed:04d}%")


async def _reset_history(conn: asyncpg.Connection, dataset: DemoDataset) -> None:
    skus = [observation.sku for observation in dataset.observations]
    await conn.execute("DELETE FROM price_history WHERE sku = ANY($1::text[])", skus)


async def reset_demo_data(
    database_url: str,
    timescale_url: str,
    dataset: DemoDataset,
) -> None:
    core_conn = await asyncpg.connect(database_url)
    history_conn = await asyncpg.connect(timescale_url)
    try:
        async with core_conn.transaction():
            await _reset_core(core_conn, dataset)
        async with history_conn.transaction():
            await _reset_history(history_conn, dataset)
    finally:
        await core_conn.close()
        await history_conn.close()


async def insert_demo_data(
    database_url: str,
    timescale_url: str,
    dataset: DemoDataset,
    reset_first: bool = True,
) -> dict[str, int]:
    core_conn = await asyncpg.connect(database_url)
    history_conn = await asyncpg.connect(timescale_url)
    try:
        if reset_first:
            async with core_conn.transaction():
                await _reset_core(core_conn, dataset)
            async with history_conn.transaction():
                await _reset_history(history_conn, dataset)

        item_ids: dict[str, object] = {}
        latest_by_sku: dict[str, PriceObservation] = {}
        for observation in dataset.observations:
            current = latest_by_sku.get(observation.sku)
            if current is None or observation.timestamp > current.timestamp:
                latest_by_sku[observation.sku] = observation
        end_timestamp = datetime.combine(dataset.end_date, time(12), tzinfo=timezone.utc)
        async with core_conn.transaction():
            for index, product in enumerate(dataset.products, start=1):
                user_id = await core_conn.fetchval(
                    "INSERT INTO users (phone, password_hash, salt, tier) VALUES ($1, $2, $3, 'free') RETURNING id",
                    _demo_user_phone(dataset.seed, index), "demo-password-hash", "demo-salt",
                )
                item_id = await core_conn.fetchval(
                    "INSERT INTO tracked_items (user_id, canonical_product_id, specs, target_price, is_active) VALUES ($1, $2, $3, $4, TRUE) RETURNING id",
                    user_id, product.product_id, json.dumps({"name": product.name, "category": product.category, "scenario": product.scenario}), product.baseline_egp * Decimal("0.85"),
                )
                item_ids[product.product_id] = item_id
                for store_id in STORES:
                    sku = f"{product.product_id}-{store_id}"
                    url = f"https://demo.{store_id}.example/products/{sku}"
                    await core_conn.execute(
                        "INSERT INTO tracked_item_stores (tracked_item_id, store_id, store_sku, store_url, is_active) VALUES ($1, $2, $3, $4, TRUE)",
                        item_id, store_id, sku, url,
                    )
                    latest = latest_by_sku[sku]
                    await core_conn.execute(
                        "INSERT INTO current_prices (tracked_item_id, store_id, price_usd, price_local, currency, in_stock, last_updated) VALUES ($1, $2, $3, $4, 'EGP', $5, $6)",
                        item_id, store_id, latest.price_usd, latest.price_local, latest.in_stock, latest.timestamp,
                    )
                lowest = min((observation for observation in dataset.observations if observation.product_id == product.product_id and observation.timestamp == end_timestamp), key=lambda observation: observation.price_usd, default=None)
                if lowest is None:
                    lowest = min((observation for observation in dataset.observations if observation.product_id == product.product_id), key=lambda observation: observation.price_usd)
                await core_conn.execute(
                    "INSERT INTO lowest_prices (tracked_item_id, store_id, price_usd, price_local, currency, url, last_updated) VALUES ($1, $2, $3, $4, 'EGP', $5, $6)",
                    item_id, lowest.store_id, lowest.price_usd, lowest.price_local, lowest.source_url, lowest.timestamp,
                )

        await history_conn.executemany(
            "INSERT INTO price_history (time, sku, store_id, price_usd, price_local, currency, in_stock, source_url) VALUES ($1, $2, $3, $4, $5, 'EGP', $6, $7) ON CONFLICT (time, sku, store_id) DO UPDATE SET price_usd = EXCLUDED.price_usd, price_local = EXCLUDED.price_local, in_stock = EXCLUDED.in_stock, source_url = EXCLUDED.source_url",
            [(observation.timestamp, observation.sku, observation.store_id, observation.price_usd, observation.price_local, observation.in_stock, observation.source_url) for observation in dataset.observations],
        )
        return {"products": len(dataset.products), "stores": len(STORES), "observations": len(dataset.observations)}
    finally:
        await core_conn.close()
        await history_conn.close()


def _database_urls(args: argparse.Namespace) -> tuple[str, str]:
    database_url = args.database_url or os.getenv("DATABASE_URL")
    timescale_url = args.timescale_url or os.getenv("TIMESCALE_URL")
    if not database_url or not timescale_url:
        raise SystemExit("DATABASE_URL and TIMESCALE_URL are required")
    return database_url, timescale_url


async def _run(args: argparse.Namespace) -> None:
    dataset = generate_dataset(args.seed, date.fromisoformat(args.start_date), args.days)
    database_url, timescale_url = _database_urls(args)
    if args.command == "reset":
        await reset_demo_data(database_url, timescale_url, dataset)
        print("Reset demo data")
        return
    counts = await insert_demo_data(database_url, timescale_url, dataset, reset_first=True)
    print(f"Generated {counts['products']} products, {counts['stores']} stores, {counts['observations']} observations")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "regenerate", "reset"), nargs="?", default="generate")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE.isoformat())
    parser.add_argument("--database-url")
    parser.add_argument("--timescale-url")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
