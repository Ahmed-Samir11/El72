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
    assert "SKU1" in msg
    assert "100.00 جنيه" in msg


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
    assert "Previous price: 1,000.00 جنيه" in msg
    assert "Current price: 800.00 جنيه" in msg
    assert "Discount: 20%" in msg
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
        {"id": 16, "phone": "+201111", "preferred_language": "ar"},
        {"id": 17, "phone": "+201222", "preferred_language": "ar"},
        {"id": 18, "phone": "+201333", "preferred_language": "ar"},
    ]
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    cursor_cm.__exit__.return_value = False

    conn = MagicMock()
    conn.closed = False
    conn.cursor.side_effect = [MagicMock(), cursor_cm]

    with patch("services.whatsapp.sender.get_db_connection", return_value=conn):
        result = sender.get_subscribers_for_sku("B0ABC")

    assert result == [
        (16, "+201111", "ar", "Customer"),
        (17, "+201222", "ar", "Customer"),
        (18, "+201333", "ar", "Customer"),
    ]
    cursor.execute.assert_called_once()


def test_format_price_alert_localized_arabic():
    msg = sender.format_price_alert({"name": "محمد", "sku": "SKU1", "product_title": "Laptop", "price": 1000, "original_price": 1200, "discount_percent": 20, "url": "https://example.com/p"}, language="ar")
    assert "مرحباً محمد" in msg
    assert "وجدنا عرضاً جيداً على Laptop" in msg
    assert "السعر السابق: 1,200.00 جنيه" in msg
    assert "السعر الحالي" in msg
    assert "خصم" in msg
    assert "https://example.com/p" in msg


def test_format_price_alert_arabic_maps_dynamic_values():
    msg = sender.format_price_alert(
        {
            "name": "أحمد",
            "product_title": "Lenovo Legion 5",
            "price": 36210.39,
            "original_price": 47115.75,
            "discount_percent": 23.15,
            "url": "https://example.com/deal",
        },
        language="ar",
    )
    assert "أحمد" in msg
    assert "Lenovo Legion 5" in msg
    assert "47,115.75 جنيه" in msg
    assert "36,210.39 جنيه" in msg
    assert "23.15%" in msg
    assert "https://example.com/deal" in msg


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

    assert result == [(9, "+20999", "en", "Customer")]


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

    payload = {"sku": "SKU1", "price": 50, "user_id": 16, "user_phone": "+201234"}
    with patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(return_value=True),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    send_mock.assert_awaited()
    sender.redis_client.setex.assert_awaited()
    assert sender.redis_client.setex.await_args.args[0] == "alert_sent:16:SKU1"
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_dedup_skips():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = True

    payload = {"sku": "SKU1", "price": 50, "user_id": 16, "user_phone": "+201234"}
    with patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(return_value=True),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    send_mock.assert_not_awaited()
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_send_failure():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = False

    payload = {"sku": "SKU1", "price": 50, "user_id": 16, "user_phone": "+201234"}
    with patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(return_value=False),
    ):
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    sender.redis_client.setex.assert_not_awaited()
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_ignores_non_egyptian_direct_user():
    sender.redis_client = AsyncMock()
    payload = {
        "sku": "SKU1",
        "price": 50,
        "user_id": 19,
        "user_phone": "+37000000000",
        "preferred_language": "lt",
    }
    with patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(return_value=True),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    send_mock.assert_not_awaited()
    sender.redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_sends_each_subscriber_language_independently():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = False
    subscribers = [
        (16, "+201", "ar"),
        (17, "+202", "ar"),
        (18, "+203", "ar"),
    ]
    payload = {"sku": "SKU1", "price": 50}

    async def send(_phone, _payload, language):
        if _phone == "+202":
            return False
        return True

    with patch(
        "services.whatsapp.sender.get_subscribers_for_sku",
        return_value=subscribers,
    ), patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(side_effect=send),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    assert [call.args[2] for call in send_mock.await_args_list] == ["ar", "ar", "ar"]
    assert send_mock.await_count == 3
    assert sender.redis_client.xack.await_count == 1


def test_normalize_phone_adds_plus():
    assert sender.normalize_phone("201000000001") == "+201000000001"
    assert sender.normalize_phone("+201000000001") == "+201000000001"


def test_plain_text_message_contains_all_deal_values():
    message = sender.format_price_alert(
        {
            "name": "محمد",
            "product_title": "Lenovo Legion 5",
            "price": 36210.39,
            "original_price": 47115.75,
            "discount_percent": 23.15,
            "url": "https://example.com/deal/lenovo-legion-5",
        },
        language="ar",
    )
    assert message.index("محمد") < message.index("Lenovo Legion 5")
    assert message.index("47,115.75 جنيه") < message.index("36,210.39 جنيه")
    assert message.index("36,210.39 جنيه") < message.index("23.15%")
    assert message.index("23.15%") < message.index("https://example.com/deal/lenovo-legion-5")


@pytest.mark.asyncio
async def test_process_message_uses_name_language_per_subscriber():
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = False
    subscribers = [
        (16, "+201111111111", "ar", "محمد"),
        (17, "+201222222222", "ar", "لؤي"),
        (18, "+201333333333", "ar", "أحمد"),
    ]
    payload = {
        "sku": "SKU1",
        "price": 36210.39,
        "original_price": 47115.75,
        "discount_percent": 23.15,
        "product_title": "Lenovo Legion 5",
        "url": "https://example.com/deal/lenovo-legion-5",
    }

    with patch(
        "services.whatsapp.sender.get_subscribers_for_sku",
        return_value=subscribers,
    ), patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(return_value=True),
    ) as send_mock:
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    assert send_mock.await_count == 3
    first_payload = send_mock.await_args_list[0].args[1]
    second_payload = send_mock.await_args_list[1].args[1]
    third_payload = send_mock.await_args_list[2].args[1]
    assert first_payload["name"] == "محمد"
    assert first_payload["preferred_language"] == "ar"
    assert second_payload["name"] == "لؤي"
    assert second_payload["preferred_language"] == "ar"
    assert third_payload["name"] == "أحمد"
    assert third_payload["preferred_language"] == "ar"


@pytest.mark.asyncio
async def test_send_whatsapp_price_alert_success():
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
        ok = await sender.send_whatsapp_price_alert(
            "201000000001",
            {"name": "محمد", "sku": "S1", "price": 10, "original_price": 20, "discount_percent": 50, "url": "https://x"},
            language="ar",
        )
    assert ok is True
    sent_json = mock_client.post.await_args.kwargs["json"]
    assert sent_json["type"] == "text"
    assert sent_json["to"] == "+201000000001"
    assert sent_json["text"]["preview_url"] is True
    assert "مرحباً محمد" in sent_json["text"]["body"]
    assert "type" not in sent_json.get("template", {})


@pytest.mark.asyncio
async def test_process_message_exception_no_ack():
    sender.redis_client = AsyncMock()
    # Invalid JSON triggers processing error path
    await sender.process_message("1-0", {b"payload": b"{not-json"})
    sender.redis_client.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_counts_subscriber_exception_as_failure(caplog):
    sender.redis_client = AsyncMock()
    sender.redis_client.exists.return_value = False
    subscribers = [(16, "+201111111111", "ar", "محمد")]
    payload = {
        "sku": "SKU1",
        "product_title": "El72 Test Product",
        "original_price": 1000,
        "price": 750,
        "discount_percent": 25,
        "url": "https://example.com/deal",
    }

    with patch(
        "services.whatsapp.sender.get_subscribers_for_sku",
        return_value=subscribers,
    ), patch(
        "services.whatsapp.sender.send_whatsapp_price_alert",
        new=AsyncMock(side_effect=RuntimeError("Meta request failed")),
    ):
        await sender.process_message("1-0", {"payload": json.dumps(payload)})

    sender.redis_client.xack.assert_awaited_once()


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
