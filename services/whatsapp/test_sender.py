"""Unit tests for WhatsApp sender service (all externals mocked)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as aioredis

import services.whatsapp.sender as sender


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level connection globals between tests."""
    sender.redis_client = None
    sender.db_conn = None
    yield
    sender.redis_client = None
    sender.db_conn = None


def test_format_price_alert_minimal():
    msg = sender.format_price_alert({"sku": "SKU1", "price": 100})
    assert "El72 Price Alert" in msg
    assert "Product: SKU1" in msg
    assert "100 EGP" in msg


def test_format_price_alert_full():
    msg = sender.format_price_alert(
        {
            "sku": "SKU1",
            "product_title": "Laptop Pro",
            "price": 800,
            "original_price": 1000,
            "discount_percent": 20,
            "url": "https://example.com/p",
            "store": "Amazon Egypt",
        }
    )
    assert "Laptop Pro" in msg
    assert "Amazon Egypt" in msg
    assert "Discount: 20%" in msg
    assert "You save: 200 EGP" in msg
    assert "https://example.com/p" in msg


def test_get_db_connection_reuses_open_conn():
    mock_conn = MagicMock()
    mock_conn.closed = False
    sender.db_conn = mock_conn

    with patch("services.whatsapp.sender.psycopg2.connect") as connect:
        conn = sender.get_db_connection()
        assert conn is mock_conn
        connect.assert_not_called()


def test_get_db_connection_creates_when_missing():
    mock_conn = MagicMock()
    with patch("services.whatsapp.sender.psycopg2.connect", return_value=mock_conn) as connect:
        conn = sender.get_db_connection()
        assert conn is mock_conn
        connect.assert_called_once_with(sender.DATABASE_URL)


def test_get_subscribers_for_sku_success():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"id": 1, "phone": "+201111"},
        {"id": 2, "phone": "+201222"},
    ]
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    cursor_cm.__exit__.return_value = False

    conn = MagicMock()
    conn.closed = False
    conn.cursor.side_effect = [MagicMock(), cursor_cm]

    with patch("services.whatsapp.sender.get_db_connection", return_value=conn):
        result = sender.get_subscribers_for_sku("B0ABC")

    assert result == [(1, "+201111"), (2, "+201222")]
    cursor.execute.assert_called_once()


def test_get_subscribers_reconnects_on_dead_connection():
    dead_conn = MagicMock()
    dead_conn.closed = False
    dead_conn.cursor.return_value.execute.side_effect = Exception("connection lost")

    cursor = MagicMock()
    cursor.fetchall.return_value = [{"id": 9, "phone": "+20999"}]
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    cursor_cm.__exit__.return_value = False

    fresh_conn = MagicMock()
    fresh_conn.closed = False
    fresh_conn.cursor.return_value = cursor_cm

    with patch(
        "services.whatsapp.sender.get_db_connection",
        side_effect=[dead_conn, fresh_conn],
    ):
        result = sender.get_subscribers_for_sku("SKU")

    assert result == [(9, "+20999")]


def test_get_subscribers_returns_empty_on_error():
    with patch(
        "services.whatsapp.sender.get_db_connection",
        side_effect=Exception("db down"),
    ):
        assert sender.get_subscribers_for_sku("SKU") == []


@pytest.mark.asyncio
async def test_ensure_consumer_group_creates():
    sender.redis_client = AsyncMock()
    await sender.ensure_consumer_group()
    sender.redis_client.xgroup_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_consumer_group_busygroup_ok():
    sender.redis_client = AsyncMock()
    sender.redis_client.xgroup_create.side_effect = aioredis.ResponseError(
        "BUSYGROUP Consumer Group name already exists"
    )
    await sender.ensure_consumer_group()


@pytest.mark.asyncio
async def test_ensure_consumer_group_other_error_raises():
    sender.redis_client = AsyncMock()
    sender.redis_client.xgroup_create.side_effect = aioredis.ResponseError("NOGROUP")
    with pytest.raises(aioredis.ResponseError):
        await sender.ensure_consumer_group()


@pytest.mark.asyncio
async def test_send_whatsapp_mock_mode():
    with patch.object(sender, "MOCK_MODE", True):
        assert await sender.send_whatsapp_message("20111", "hi") is True


@pytest.mark.asyncio
async def test_send_whatsapp_missing_credentials():
    with patch.object(sender, "MOCK_MODE", False), patch.object(
        sender, "ACCESS_TOKEN", ""
    ), patch.object(sender, "PHONE_NUMBER_ID", ""):
        assert await sender.send_whatsapp_message("20111", "hi") is False


@pytest.mark.asyncio
async def test_send_whatsapp_api_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"messages": [{"id": "wamid.1"}]}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch.object(sender, "MOCK_MODE", False), patch.object(
        sender, "ACCESS_TOKEN", "token"
    ), patch.object(sender, "PHONE_NUMBER_ID", "123"), patch(
        "services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client
    ):
        assert await sender.send_whatsapp_message("20111", "hello") is True


@pytest.mark.asyncio
async def test_send_whatsapp_api_error_status():
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "bad request"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch.object(sender, "MOCK_MODE", False), patch.object(
        sender, "ACCESS_TOKEN", "token"
    ), patch.object(sender, "PHONE_NUMBER_ID", "123"), patch(
        "services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client
    ):
        assert await sender.send_whatsapp_message("20111", "hello") is False


@pytest.mark.asyncio
async def test_send_whatsapp_api_exception():
    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("network")
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch.object(sender, "MOCK_MODE", False), patch.object(
        sender, "ACCESS_TOKEN", "token"
    ), patch.object(sender, "PHONE_NUMBER_ID", "123"), patch(
        "services.whatsapp.sender.httpx.AsyncClient", return_value=mock_client
    ):
        assert await sender.send_whatsapp_message("20111", "hello") is False


@pytest.mark.asyncio
async def test_process_message_no_sku_acks():
    sender.redis_client = AsyncMock()
    await sender.process_message("1-0", {b"payload": json.dumps({"price": 10}).encode()})
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_unwrapped_no_subscribers():
    sender.redis_client = AsyncMock()
    with patch("services.whatsapp.sender.get_subscribers_for_sku", return_value=[]):
        await sender.process_message(
            "1-0",
            {b"sku": b"SKU1", b"price": b"100"},
        )
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_user_phone_success():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = False

    payload = {"sku": "SKU1", "price": 50, "user_phone": "+201234"}
    with patch(
        "services.whatsapp.sender.send_whatsapp_message",
        new=AsyncMock(return_value=True),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    send_mock.assert_awaited()
    sender.redis_client.setex.assert_awaited()
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_dedup_skips():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = True

    payload = {"sku": "SKU1", "price": 50, "user_phone": "+201234"}
    with patch(
        "services.whatsapp.sender.send_whatsapp_message",
        new=AsyncMock(return_value=True),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    send_mock.assert_not_awaited()
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_send_failure():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = False

    payload = {"sku": "SKU1", "price": 50, "user_phone": "+201234"}
    with patch(
        "services.whatsapp.sender.send_whatsapp_message",
        new=AsyncMock(return_value=False),
    ):
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    sender.redis_client.setex.assert_not_awaited()
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_exception_no_ack():
    sender.redis_client = AsyncMock()
    # Invalid JSON triggers processing error path
    await sender.process_message("1-0", {b"payload": b"{not-json"})
    sender.redis_client.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_loop_processes_then_cancels():
    sender.redis_client = AsyncMock()
    sender.redis_client.xreadgroup.side_effect = [
        [("stream:confirmed_deals", [("1-0", {b"payload": b'{"sku":"S"}'})])],
        asyncio.CancelledError(),
    ]

    with patch(
        "services.whatsapp.sender.ensure_consumer_group", new=AsyncMock()
    ), patch(
        "services.whatsapp.sender.process_message", new=AsyncMock()
    ) as process:
        await sender.consume_loop()

    process.assert_awaited_once()


@pytest.mark.asyncio
async def test_consume_loop_backoff_on_error():
    sender.redis_client = AsyncMock()
    sender.redis_client.xreadgroup.side_effect = [
        Exception("redis blip"),
        asyncio.CancelledError(),
    ]

    with patch(
        "services.whatsapp.sender.ensure_consumer_group", new=AsyncMock()
    ), patch("services.whatsapp.sender.asyncio.sleep", new=AsyncMock()) as sleep:
        await sender.consume_loop()

    sleep.assert_awaited()


@pytest.mark.asyncio
async def test_main_db_failure_exits():
    with patch(
        "services.whatsapp.sender.get_db_connection",
        side_effect=Exception("no db"),
    ), patch("services.whatsapp.sender.sys.exit", side_effect=SystemExit(1)) as exit_mock:
        with pytest.raises(SystemExit):
            await sender.main()
        exit_mock.assert_called_with(1)


@pytest.mark.asyncio
async def test_main_redis_failure_exits():
    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = Exception("no redis")

    with patch(
        "services.whatsapp.sender.get_db_connection", return_value=MagicMock(closed=False)
    ), patch(
        "services.whatsapp.sender.aioredis.from_url", return_value=mock_redis
    ), patch("services.whatsapp.sender.sys.exit", side_effect=SystemExit(1)):
        with pytest.raises(SystemExit):
            await sender.main()


@pytest.mark.asyncio
async def test_main_success_path():
    mock_db = MagicMock()
    mock_db.closed = False
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True

    with patch.object(
        sender, "DATABASE_URL", "postgresql://u:p@localhost:5432/db"
    ), patch(
        "services.whatsapp.sender.get_db_connection", return_value=mock_db
    ), patch(
        "services.whatsapp.sender.aioredis.from_url", return_value=mock_redis
    ), patch(
        "services.whatsapp.sender.consume_loop", new=AsyncMock()
    ):
        await sender.main()

    mock_redis.aclose.assert_awaited()
    mock_db.close.assert_called_once()
