import pytest
from unittest.mock import AsyncMock, MagicMock
from services.common.redis_client import RedisStreamClient

@pytest.mark.asyncio
async def test_create_client():
    # Mock redis
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mock_redis.from_url = MagicMock(return_value=mock_redis)

    # Since it's singleton, reset
    RedisStreamClient._instance = None

    # Mock the from_url
    import redis.asyncio as aioredis
    original_from_url = aioredis.from_url
    aioredis.from_url = MagicMock(return_value=mock_redis)

    client = await RedisStreamClient.create("redis://localhost:6379")
    assert client is not None
    assert client._redis == mock_redis

    # Restore
    aioredis.from_url = original_from_url

def test_singleton():
    # Test that it's singleton
    assert RedisStreamClient._instance is not None

# More tests would require mocking more, but keeping simple