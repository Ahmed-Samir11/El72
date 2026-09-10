from collections import defaultdict
from datetime import timezone
from decimal import Decimal
import os
from dataclasses import replace
from argparse import Namespace
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.analyzer.seed_data import (
    DEFAULT_DAYS,
    DEFAULT_SEED,
    PRODUCTS,
    STORES,
    generate_dataset,
    insert_demo_data,
    reset_demo_data,
)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _database_mocks():
    core = AsyncMock()
    history = AsyncMock()
    core.transaction = MagicMock(return_value=_Transaction())
    history.transaction = MagicMock(return_value=_Transaction())
    core.fetchval.side_effect = list(range(1, 25))
    return core, history


def test_generation_is_deterministic():
    assert generate_dataset() == generate_dataset(DEFAULT_SEED)


def test_dataset_shape_and_dates():
    dataset = generate_dataset()
    assert len(dataset.products) == 12
    assert len(dataset.observations) == 12 * len(STORES) * DEFAULT_DAYS
    assert dataset.start_date.isoformat() == "2025-09-01"
    assert dataset.end_date.isoformat() == "2025-11-29"
    assert all(observation.timestamp.tzinfo == timezone.utc for observation in dataset.observations)
    assert min(observation.timestamp.date() for observation in dataset.observations) == dataset.start_date
    assert max(observation.timestamp.date() for observation in dataset.observations) == dataset.end_date


def test_prices_and_relationships_are_valid():
    dataset = generate_dataset()
    product_ids = {product.product_id for product in dataset.products}
    assert product_ids
    assert {observation.store_id for observation in dataset.observations} == set(STORES)
    assert all(observation.product_id in product_ids for observation in dataset.observations)
    assert all(observation.price_local > 0 for observation in dataset.observations)
    assert all(observation.price_usd > 0 for observation in dataset.observations)
    assert len({(observation.timestamp, observation.sku, observation.store_id) for observation in dataset.observations}) == len(dataset.observations)


def _by_product(dataset):
    grouped = defaultdict(list)
    for observation in dataset.observations:
        grouped[observation.product_id].append(observation)
    return grouped


def test_required_scenarios_exist():
    dataset = generate_dataset()
    grouped = _by_product(dataset)
    genuine = grouped["demo-el72-genuine-laptop"]
    genuine_prices = [observation.price_local for observation in genuine]
    assert min(genuine_prices) < Decimal("40000")
    assert max(genuine_prices) > Decimal("45000")

    fake = grouped["demo-el72-fake-phone"]
    inflated = [observation for observation in fake if 48 <= observation.timestamp.timetuple().tm_yday - dataset.start_date.timetuple().tm_yday <= 54]
    advertised = [observation for observation in fake if observation.advertised_reference_price is not None]
    assert inflated and advertised
    assert all(observation.advertised_reference_price > observation.price_local for observation in advertised)

    cross_store_day = [observation for observation in grouped["demo-el72-cross-store-tv"] if observation.timestamp.date() == dataset.end_date]
    assert max(observation.price_local for observation in cross_store_day) - min(observation.price_local for observation in cross_store_day) > Decimal("1000")

    seasonal = grouped["demo-el72-gaming-monitor"]
    first_week = [observation.price_local for observation in seasonal if observation.timestamp.day <= 7]
    event_week = [observation.price_local for observation in seasonal if 18 <= observation.timestamp.day <= 28 and observation.timestamp.month == 11]
    assert sum(event_week) / len(event_week) < sum(first_week) / len(first_week)


def test_inflation_recovery_volatility_and_stability_are_distinct():
    grouped = _by_product(generate_dataset())
    inflation = grouped["demo-el72-inflation-washing"]
    stable = grouped["demo-el72-stable-headphones"]
    volatile = grouped["demo-el72-volatile-gpu"]
    assert inflation[-1].price_local > inflation[0].price_local
    assert max(observation.price_local for observation in volatile) - min(observation.price_local for observation in volatile) > Decimal("10000")
    stable_range = max(observation.price_local for observation in stable) - min(observation.price_local for observation in stable)
    assert stable_range < Decimal("1000")


@pytest.mark.asyncio
async def test_insert_and_reset_use_scoped_demo_database_operations():
    product = PRODUCTS[0]
    dataset = generate_dataset(days=1, products=[product])
    core, history = _database_mocks()
    with patch("services.analyzer.seed_data.asyncpg.connect", side_effect=[core, history]):
        counts = await insert_demo_data("postgres://core", "postgres://history", dataset)
    assert counts == {"products": 1, "stores": 4, "observations": 4}
    assert core.fetchval.await_count == 2
    assert core.execute.await_count == 11
    history.executemany.assert_awaited_once()
    core.close.assert_awaited_once()
    history.close.assert_awaited_once()

    core, history = _database_mocks()
    with patch("services.analyzer.seed_data.asyncpg.connect", side_effect=[core, history]):
        await reset_demo_data("postgres://core", "postgres://history", dataset)
    assert core.execute.await_count == 2
    assert history.execute.await_count == 1
    core.close.assert_awaited_once()
    history.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_insert_falls_back_to_all_history_when_end_date_has_no_observation():
    dataset = generate_dataset(days=1, products=[PRODUCTS[0]])
    dataset = replace(dataset, end_date=dataset.end_date.replace(day=2))
    core, history = _database_mocks()
    with patch("services.analyzer.seed_data.asyncpg.connect", side_effect=[core, history]):
        counts = await insert_demo_data("postgres://core", "postgres://history", dataset)
    assert counts["products"] == 1
    assert core.execute.await_count == 11


def test_generate_rejects_nonpositive_days():
    with pytest.raises(ValueError, match="days must be positive"):
        generate_dataset(days=0)


def test_database_urls_require_both_connections():
    from services.analyzer.seed_data import _database_urls

    with pytest.raises(SystemExit, match="DATABASE_URL and TIMESCALE_URL"):
        _database_urls(Namespace(database_url=None, timescale_url=None))

    assert _database_urls(Namespace(database_url="core", timescale_url="history")) == (
        "core",
        "history",
    )


@pytest.mark.asyncio
async def test_cli_run_supports_reset_and_generation_commands(capsys):
    from services.analyzer import seed_data

    args = Namespace(
        command="reset",
        seed=DEFAULT_SEED,
        days=1,
        start_date="2025-09-01",
        database_url="core",
        timescale_url="history",
    )
    with patch.object(seed_data, "reset_demo_data", new=AsyncMock()) as reset:
        await seed_data._run(args)
    reset.assert_awaited_once()
    assert "Reset demo data" in capsys.readouterr().out

    args.command = "generate"
    with patch.object(seed_data, "insert_demo_data", new=AsyncMock(return_value={"products": 1, "stores": 4, "observations": 4})) as insert:
        await seed_data._run(args)
    insert.assert_awaited_once()
    assert "Generated 1 products" in capsys.readouterr().out


def test_cli_main_parses_explicit_options():
    from services.analyzer import seed_data

    original_argv = sys.argv
    sys.argv = [
        "seed_data",
        "reset",
        "--seed",
        "9",
        "--days",
        "2",
        "--start-date",
        "2025-10-01",
        "--database-url",
        "core",
        "--timescale-url",
        "history",
    ]

    def close_coroutine(coro):
        coro.close()

    try:
        with patch("services.analyzer.seed_data.asyncio.run", side_effect=close_coroutine) as run:
            seed_data.main()
        run.assert_called_once()
    finally:
        sys.argv = original_argv


@pytest.mark.asyncio
async def test_database_insertion_and_query_when_configured():
    database_url = os.getenv("DEMO_TEST_DATABASE_URL")
    timescale_url = os.getenv("DEMO_TEST_TIMESCALE_URL")
    if not database_url or not timescale_url:
        pytest.skip("Set DEMO_TEST_DATABASE_URL and DEMO_TEST_TIMESCALE_URL for database integration")

    dataset = generate_dataset(days=3)
    counts = await insert_demo_data(database_url, timescale_url, dataset)
    assert counts == {"products": 12, "stores": 4, "observations": 144}

    import asyncpg

    conn = await asyncpg.connect(timescale_url)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM price_history WHERE sku LIKE 'demo-el72-%'")
        assert count == 144
    finally:
        await conn.close()
        await reset_demo_data(database_url, timescale_url, dataset)
