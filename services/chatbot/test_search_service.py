"""Unit tests for the chatbot search service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.chatbot.search_service import (
    STORES,
    ChatbotSearchService,
    CrawlOutcome,
    SearchResultItem,
    SearchResultsSchema,
    parse_intent,
)


@pytest.fixture
def search_service(permissive_robots):
    """Create a search service instance that never fetches robots.txt."""
    service = ChatbotSearchService()
    service.robots = permissive_robots
    return service


def test_parse_intent_with_price_filter():
    """Test intent parsing extracts price filter correctly."""
    result = parse_intent("gaming laptop under 50000 EGP")
    assert result["query"] == "gaming laptop"
    assert result["max_price"] == 50000.0


def test_parse_intent_without_price():
    """Test intent parsing without price filter."""
    result = parse_intent("iPhone 15 Pro Max")
    assert result["query"] == "iPhone 15 Pro Max"
    assert result["max_price"] is None


def test_parse_intent_below_price():
    """Test intent parsing with 'below' keyword."""
    result = parse_intent("Samsung TV below 30000")
    assert result["query"] == "Samsung TV"
    assert result["max_price"] == 30000.0


def test_parse_intent_max_price():
    """Test intent parsing with 'max' keyword."""
    result = parse_intent("laptop max 40000")
    assert result["query"] == "laptop"
    assert result["max_price"] == 40000.0


def test_parse_intent_standalone_number():
    """Test intent parsing with standalone number at end."""
    result = parse_intent("laptop 50000 EGP")
    assert result["query"] == "laptop"
    assert result["max_price"] == 50000.0


def test_parse_intent_empty_query():
    """Test intent parsing with only a price filter."""
    result = parse_intent("under 50000 EGP")
    assert result["query"] == ""
    assert result["max_price"] == 50000.0


def test_parse_arabic_intent():
    """Test Arabic intent includes translated and display queries."""
    result = parse_intent("عايز شاشات 2k بسعر أقل من 12 ألف")
    assert result["query"] == "monitors 2k"
    assert result["display_query"] == "شاشات 2k"
    assert result["max_price"] == 12000.0
    assert result["language"] == "ar"


@pytest.mark.asyncio
async def test_search_service_init(search_service):
    """Test that the search service initializes correctly."""
    assert search_service.stores == STORES
    assert len(search_service.stores) > 0
    await search_service.close()


@pytest.mark.asyncio
async def test_search_with_mocked_extract(search_service):
    """Test full search flow with mocked extraction."""

    # Mock _extract_search_results to return results
    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return MagicMock(
                products=[
                    MagicMock(
                        title="Gaming Laptop",
                        url="/product/123",
                        price=55000.0,
                        currency="EGP",
                        image_url="https://example.com/image.jpg",
                        in_stock=True,
                    )
                ]
            )
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("gaming laptop", max_price=60000)

    assert len(results) == 1
    assert results[0]["title"] == "Gaming Laptop"
    assert results[0]["price"] == 55000.0
    assert results[0]["store_id"] == "amazon_eg"

    await search_service.close()


@pytest.mark.asyncio
async def test_search_price_filter(search_service):
    """Test that price filter is applied in search."""

    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return MagicMock(
                products=[
                    MagicMock(
                        title="Laptop A",
                        url="/product/a",
                        price=50000.0,
                        currency="EGP",
                        image_url=None,
                        in_stock=True,
                    ),
                    MagicMock(
                        title="Laptop B",
                        url="/product/b",
                        price=80000.0,
                        currency="EGP",
                        image_url=None,
                        in_stock=True,
                    ),
                ]
            )
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("laptop", max_price=60000)

    # Only Laptop A (50000) should pass the filter, not Laptop B (80000)
    assert len(results) == 1
    assert results[0]["title"] == "Laptop A"
    assert results[0]["price"] == 50000.0

    await search_service.close()


@pytest.mark.asyncio
async def test_search_no_results(search_service):
    """Test search when no results are found."""

    async def mock_extract(query, store, **_):
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("nonexistent product xyz123")

    assert results == []

    await search_service.close()


@pytest.mark.asyncio
async def test_search_with_intent(search_service):
    """Test search_with_intent parses and searches."""

    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return MagicMock(
                products=[
                    MagicMock(
                        title="Gaming Laptop",
                        url="/product/123",
                        price=45000.0,
                        currency="EGP",
                        image_url=None,
                        in_stock=True,
                    )
                ]
            )
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    result = await search_service.search_with_intent("gaming laptop under 50000 EGP")

    assert result["query"] == "gaming laptop"
    assert result["max_price"] == 50000.0
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Gaming Laptop"

    await search_service.close()


def test_search_result_item_validation():
    """Test SearchResultItem validation."""
    item = SearchResultItem(
        title="Test Product",
        url="/product/123",
        price=100.0,
        currency="EGP",
        image_url="https://example.com/image.jpg",
        in_stock=True,
    )
    assert item.title == "Test Product"
    assert item.price == 100.0


def test_search_results_schema_validation():
    """Test SearchResultsSchema validation."""
    schema = SearchResultsSchema(
        products=[
            SearchResultItem(
                title="Test Product",
                url="/product/123",
                price=100.0,
                currency="EGP",
            )
        ],
        total_results=1,
    )
    assert len(schema.products) == 1
    assert schema.total_results == 1


@pytest.mark.parametrize(
    "message, query, min_price, max_price",
    [
        ("I want laptops in the range 40k egp to 70k egp", "laptops", 40000, 70000),
        ("laptops from 40k to 70k", "laptops", 40000, 70000),
        ("gaming laptop between 40,000 and 70,000 EGP", "gaming laptop", 40000, 70000),
        # Reversed bounds are put in order.
        ("laptop 70k-40k", "laptop", 40000, 70000),
        ("monitor over 10k", "monitor", 10000, None),
        ("rtx 4060 laptop under 55k", "rtx 4060 laptop", None, 55000),
    ],
)
def test_parse_intent_price_ranges(message, query, min_price, max_price):
    result = parse_intent(message)
    assert result["query"] == query
    assert result["min_price"] == min_price
    assert result["max_price"] == max_price


def _product(title, price, relevant=True):
    return SearchResultItem(
        title=title,
        url=f"/p/{title.replace(' ', '-')}",
        price=price,
        relevant=relevant,
    )


@pytest.mark.asyncio
async def test_search_applies_min_and_max_price(search_service):
    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return SearchResultsSchema(
                products=[
                    _product("Laptop Cheap", 30000),
                    _product("Laptop Mid", 55000),
                    _product("Laptop Pricey", 90000),
                ]
            )
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("laptop", max_price=70000, min_price=40000)

    assert [r["title"] for r in results] == ["Laptop Mid"]
    await search_service.close()


@pytest.mark.asyncio
async def test_search_drops_products_marked_irrelevant(search_service):
    """Featured items on a no-results page (a CPU for a laptop search) are
    dropped even though they fit the budget."""

    async def mock_extract(query, store, **_):
        if store.store_id == "elbadrgroup":
            return SearchResultsSchema(
                products=[
                    _product("AMD Ryzen 5 5600 MPK", 5999, relevant=False),
                    _product("Acer VG270 Monitor", 6799, relevant=False),
                    _product("Lenovo IdeaPad Slim 3", 45000),
                ]
            )
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("laptop")

    assert [r["title"] for r in results] == ["Lenovo IdeaPad Slim 3"]
    await search_service.close()


def test_salvage_products_from_truncated_json():
    from services.chatbot.search_service import _salvage_products_json

    truncated = (
        '{"products": [{"title": "ASUS TUF A16", "url": "/a", "price": 86500},'
        ' {"title": "Lenovo LOQ", "url": "/b", "price": 64999},'
        ' {"title": "HP Victus", "url": "/c", "pri'
    )
    salvaged = json.loads(_salvage_products_json(truncated))
    assert [p["title"] for p in salvaged["products"]] == ["ASUS TUF A16", "Lenovo LOQ"]
    assert _salvage_products_json('{"products": [{"title": "cut') is None


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "not json at all",
        '{"items": [{"title": "A", "url": "/a"}]}',
        '{"products": []',
        '{"products": [',
        '{"products": ["A", "B"',
        '{"products": [{"title": "A", "url": "/a"',
    ],
)
def test_salvage_refuses_output_with_no_complete_product(malformed):
    from services.chatbot.search_service import _salvage_products_json

    assert _salvage_products_json(malformed) is None


def test_salvage_stops_at_the_end_of_the_products_array():
    from services.chatbot.search_service import _salvage_products_json

    # Valid up to the array, broken afterwards: the pagination object written
    # after "]" must not be recovered as a product.
    text = (
        '{"products": [{"title": "A", "url": "/a"}], '
        '"pagination": {"current_page": 1}, "total": '
    )
    salvaged = json.loads(_salvage_products_json(text))
    assert salvaged == {"products": [{"title": "A", "url": "/a"}]}


def test_salvage_keeps_nested_objects_inside_a_product():
    from services.chatbot.search_service import _salvage_products_json

    text = (
        '{"products": [{"title": "A", "url": "/a", "offers": {"price": 10}},'
        ' {"title": "B", "url": "/b", "off'
    )
    salvaged = json.loads(_salvage_products_json(text))
    assert salvaged["products"] == [
        {"title": "A", "url": "/a", "offers": {"price": 10}}
    ]


def test_focus_on_listings_skips_menu_prices_to_densest_block():
    from services.chatbot.search_service import LLM_INPUT_CHARS, _focus_on_listings

    menu = "Menu " + "x" * 3000 + " Featured CPU EGP 5,999 " + "y" * 12000
    grid = " ".join(f"Laptop {i} EGP {40000 + i:,}" for i in range(40))
    focused = _focus_on_listings(menu + grid)
    # The window lands on the grid, not the lone menu price.
    assert "Laptop 0 EGP" in focused[:LLM_INPUT_CHARS]
    assert "Featured CPU" not in focused


def test_focus_on_budget_keeps_only_in_budget_cards():
    from services.chatbot.search_service import _focus_on_budget

    cards = [
        ("Omen Pricey", 139899),
        ("Lenovo LOQ", 64999),
        ("MacBook", 92999),
        ("Acer Nitro V", 55799),
    ]
    page = "".join(
        f"[![img](https://s/{t}.jpg)](https://s/{t}) [{t}](https://s/{t}) "
        f"EGP {p:,} " + "z" * 900
        for t, p in cards
    )
    focused = _focus_on_budget(page, 40000, 70000)
    assert "Lenovo LOQ" in focused and "Acer Nitro V" in focused
    assert "Omen Pricey" not in focused and "MacBook" not in focused
    # No budget, or nothing in budget: caller falls back to the whole listing.
    assert _focus_on_budget(page, None, None) is None
    assert _focus_on_budget(page, 1, 10) is None


# ---------------------------------------------------------------------------
# Speed: caching, deterministic extraction, store health
# ---------------------------------------------------------------------------


class DenyingRobotsPolicy:
    """A robots policy that refuses every URL, for the robots-denied path."""

    def __init__(self):
        self.checked = 0

    async def is_allowed(self, url: str) -> bool:
        self.checked += 1
        return False

    async def get_declared_crawl_delay(self, url: str):
        return None


@pytest.mark.asyncio
async def test_repeat_search_is_served_from_the_cache(search_service):
    """The same question in the same session must not re-crawl every store."""
    calls = {"count": 0}

    async def mock_extract(query, store, **_):
        calls["count"] += 1
        return SearchResultsSchema(
            products=(
                [SearchResultItem(title="Lenovo LOQ Laptop", url="/loq", price=64999.0)]
                if store.store_id == "amazon_eg"
                else []
            )
        )

    search_service._extract_search_results = mock_extract

    first, first_status = await search_service._search_all_stores("laptop")
    second, second_status = await search_service._search_all_stores("laptop")

    assert calls["count"] == len(STORES)
    assert first == second
    assert [r["title"] for r in second] == ["Lenovo LOQ Laptop"]

    amazon = next(s for s in second_status if s["store_id"] == "amazon_eg")
    assert amazon["state"] == "cached"
    assert amazon["products"] == 1
    await search_service.close()


@pytest.mark.asyncio
async def test_a_refined_price_window_is_not_a_cache_hit(search_service):
    """ "under 12k" then "under 10k" are different questions, cached apart."""
    calls = {"count": 0}

    async def mock_extract(query, store, **_):
        calls["count"] += 1
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    await search_service._search_all_stores("laptop", max_price=12000)
    await search_service._search_all_stores("laptop", max_price=10000)

    assert calls["count"] == 2 * len(STORES)
    await search_service.close()


@pytest.mark.asyncio
async def test_jsonld_pages_never_reach_the_llm(search_service):
    """A store that ships JSON-LD costs one crawl, not a crawl plus an LLM slot."""
    page = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Lenovo LOQ Gaming Laptop", '
        '"url": "https://amazon.eg/d/loq", "offers": {"priceAmount": 64999}}'
        "</script>"
    )

    async def mock_crawl(url, store_id=""):
        return CrawlOutcome(html=page, status_code=200)

    search_service._crawl_page = mock_crawl

    with patch(
        "services.chatbot.search_service.LMStudioExtractionStrategy"
    ) as strategy:
        results, statuses = await search_service._search_all_stores("gaming laptop")

    assert not strategy.called
    assert [r["title"] for r in results] == ["Lenovo LOQ Gaming Laptop"] * len(STORES)
    assert all(r["price"] == 64999.0 for r in results)
    assert {s["state"] for s in statuses} == {"ok"}
    await search_service.close()


@pytest.mark.asyncio
async def test_the_llm_stays_the_fallback_for_unparseable_pages(search_service):
    """A JavaScript-only grid still gets extracted, exactly as before."""

    async def mock_crawl(url, store_id=""):
        return CrawlOutcome(html="<html><body>nothing readable</body></html>")

    search_service._crawl_page = mock_crawl

    with patch(
        "services.chatbot.search_service.LMStudioExtractionStrategy"
    ) as strategy:
        strategy.return_value.extract = AsyncMock(return_value='{"products": []}')
        results, statuses = await search_service._search_all_stores("laptop")

    assert strategy.call_count == len(STORES)
    assert results == []
    # Reachable but empty is reported as such, not as a failure.
    assert {s["state"] for s in statuses} == {"empty"}
    await search_service.close()


@pytest.mark.asyncio
async def test_a_timed_out_store_is_reported_not_dropped(search_service):
    """ "This store never answered" must be visible, not a silently short list."""

    async def mock_crawl(url, store_id=""):
        return CrawlOutcome(error="timeout after 25s")

    search_service._crawl_page = mock_crawl

    results, statuses = await search_service._search_all_stores("laptop")

    assert results == []
    assert len(statuses) == len(STORES)
    assert {s["state"] for s in statuses} == {"timeout"}
    assert statuses[0]["detail"] == "timeout after 25s"
    await search_service.close()


@pytest.mark.asyncio
async def test_robots_denied_store_is_not_crawled(search_service):
    """A disallowed path is refused before the browser is opened."""
    search_service.robots = DenyingRobotsPolicy()
    calls = {"count": 0}

    async def mock_extract(query, store, **_):
        calls["count"] += 1
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    _, statuses = await search_service._search_all_stores("laptop")

    assert calls["count"] == 0
    assert {s["state"] for s in statuses} == {"robots_denied"}
    await search_service.close()


class DeclaredDelayRobotsPolicy:
    """A robots policy that declares a Crawl-Delay of [delay] seconds."""

    def __init__(self, delay):
        self.delay = delay

    async def is_allowed(self, url: str) -> bool:
        return True

    async def get_declared_crawl_delay(self, url: str):
        return self.delay


@pytest.mark.asyncio
async def test_a_declared_crawl_delay_is_honored_exactly(search_service, monkeypatch):
    """A store asking for a pause gets exactly that pause, never a shortened one.

    Capping the wait below what robots.txt declared would be non-compliant
    crawling dressed up as compliance, so the cap is a budget limit that
    refuses the store instead (see the next test).
    """
    slept = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("services.chatbot.search_service.asyncio.sleep", record_sleep)
    monkeypatch.setattr("services.chatbot.search_service.MAX_CRAWL_DELAY", 10.0)
    search_service.robots = DeclaredDelayRobotsPolicy(2.5)

    calls = {"count": 0}

    async def mock_extract(query, store, **_):
        calls["count"] += 1
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    _, statuses = await search_service._search_all_stores("laptop")

    assert slept == [2.5] * len(STORES)
    assert calls["count"] == len(STORES)
    assert {s["state"] for s in statuses} == {"empty"}
    await search_service.close()


@pytest.mark.asyncio
async def test_a_crawl_delay_beyond_the_budget_refuses_the_store(
    search_service, monkeypatch
):
    """A delay this deployment cannot wait out is reported, not rounded down.

    The store keeps its robots.txt verdict (it is not crawled faster than asked)
    and the user sees why on /chatbot/stores, instead of getting a silently
    non-compliant crawl.
    """
    slept = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("services.chatbot.search_service.asyncio.sleep", record_sleep)
    monkeypatch.setattr("services.chatbot.search_service.MAX_CRAWL_DELAY", 5.0)
    search_service.robots = DeclaredDelayRobotsPolicy(30)

    calls = {"count": 0}

    async def mock_extract(query, store, **_):
        calls["count"] += 1
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    results, statuses = await search_service._search_all_stores("laptop")

    assert results == []
    assert slept == []
    assert calls["count"] == 0
    assert {s["state"] for s in statuses} == {"robots_denied"}
    assert "Crawl-Delay 30s" in statuses[0]["detail"]
    await search_service.close()


@pytest.mark.asyncio
async def test_a_repeatedly_failing_store_cools_down(search_service):
    """A store that keeps failing stops being crawled until it gets a retry."""
    search_service.store_health.reset()
    search_service.store_health.failure_threshold = 2
    search_service.store_health.cooldown_seconds = 600

    async def mock_extract(query, store, **_):
        return None

    search_service._extract_search_results = mock_extract

    for _ in range(2):
        await search_service._search_all_stores("laptop")

    _, statuses = await search_service._search_all_stores("laptop")
    amazon = next(s for s in statuses if s["store_id"] == "amazon_eg")

    assert amazon["state"] == "cooling"
    assert "skipped for" in amazon["detail"]
    await search_service.close()


@pytest.mark.asyncio
async def test_search_with_intent_reports_store_status(search_service):
    """The client learns the answer is partial straight from the response."""

    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return SearchResultsSchema(
                products=[
                    SearchResultItem(title="Gaming Laptop", url="/p/1", price=45000.0)
                ]
            )
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    result = await search_service.search_with_intent("gaming laptop under 50000 EGP")

    assert result["query"] == "gaming laptop"
    assert result["max_price"] == 50000.0
    assert len(result["results"]) == 1
    assert len(result["store_status"]) == len(STORES)
    await search_service.close()
