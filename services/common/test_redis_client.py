"""Expanded unit tests for RedisStreamClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ResponseError

from services.common.redis_client import RedisStreamClient


@pytest.fixture(autouse=True)
def reset_singleton():
    RedisStreamClient._instance = None
    yield
    RedisStreamClient._instance = None


@pytest.fixture
def client():
    mock_redis = AsyncMock()
    return RedisStreamClient(mock_redis), mock_redis


@pytest.mark.asyncio
async def test_redis_property(client):
    c, mock_redis = client
    assert c.redis is mock_redis


@pytest.mark.asyncio
async def test_ensure_group_success_and_busygroup(client):
    c, mock_redis = client
    await c.ensure_group("stream:a", "cg")
    mock_redis.xgroup_create.assert_awaited()

    mock_redis.xgroup_create.side_effect = ResponseError("BUSYGROUP already exists")
    await c.ensure_group("stream:a", "cg")

    mock_redis.xgroup_create.side_effect = ResponseError("OTHER")
    with pytest.raises(ResponseError):
        await c.ensure_group("stream:a", "cg")


@pytest.mark.asyncio
async def test_xadd_encodes_types(client):
    c, mock_redis = client
    mock_redis.xadd.return_value = "1-0"
    msg_id = await c.xadd(
        "stream:a",
        {"b": b"bytes", "s": "str", "obj": {"k": 1}},
        maxlen=100,
    )
    assert msg_id == "1-0"
    args, kwargs = mock_redis.xadd.await_args
    encoded = args[1]
    assert encoded["b"] == b"bytes"
    assert encoded["s"] == b"str"
    assert json.loads(encoded["obj"].decode()) == {"k": 1}
    assert kwargs.get("maxlen") == 100


@pytest.mark.asyncio
async def test_xadd_many(client):
    c, mock_redis = client
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=["1-0", "2-0"])
    mock_redis.pipeline = MagicMock(return_value=pipe)

    ids = await c.xadd_many(
        "stream:a",
        [{"s": "one"}, {"n": 2}, {"b": bytearray(b"x")}],
    )
    assert ids == ["1-0", "2-0"]
    assert pipe.xadd.call_count == 3
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_xreadgroup_and_xack(client):
    c, mock_redis = client
    mock_redis.xreadgroup.return_value = []
    mock_redis.xack.return_value = 1

    assert await c.xreadgroup("cg", "c1", {"s": ">"}, count=2, block=1000) == []
    assert await c.xack("s", "cg", "1-0") == 1
    assert await c.xack_many("s", "cg", []) == 0
    assert await c.xack_many("s", "cg", ["1-0", "2-0"]) == 1
    mock_redis.xack.assert_awaited()


@pytest.mark.asyncio
async def test_close(client):
    c, mock_redis = client
    await c.close()
    mock_redis.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_pings_redis():
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    with patch("services.common.redis_client.aioredis.from_url", return_value=mock_redis):
        client = await RedisStreamClient.create("redis://localhost:6379", password="x")
        assert client._redis is mock_redis
        # singleton reuse
        again = await RedisStreamClient.create("redis://localhost:6379")
        assert again is client
