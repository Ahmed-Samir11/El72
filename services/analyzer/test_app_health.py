import asyncio
import os

# Ensure required env vars exist before importing the app module
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from services.analyzer.app import health, settings


def test_health_endpoint_returns_expected_shape():
    res = asyncio.run(health())
    assert isinstance(res, dict)
    assert res.get("status") == "ok"
    assert "model_loaded" in res
    assert "model_meta" in res
    assert res.get("ml_method") == settings.ml_method
    # threshold should be a number
    assert isinstance(res.get("ml_threshold"), float)
