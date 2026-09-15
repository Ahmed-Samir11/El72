"""Additional ml_detector coverage."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import joblib
import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from services.analyzer import ml_detector


def test_score_prices_empty_and_mad_zero_variance():
    assert ml_detector.score_prices(None) == 0.0
    assert ml_detector.score_prices(np.array([])) == 0.0
    w = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
    assert 0.0 <= ml_detector.score_prices(w, method="mad") <= 1.0


def test_score_prices_unknown_method_returns_none_implicit():
    w = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    # method not mad/isolation falls through without return -> None
    assert ml_detector.score_prices(w, method="other") is None


def test_load_model_from_dir_with_artifact(tmp_path):
    model = IsolationForest(random_state=0)
    model.fit(np.array([[1], [2], [3], [4], [5]]))
    model_path = tmp_path / "model.joblib"
    joblib.dump(model, model_path)
    meta = {"path": str(model_path), "version": "test"}
    (tmp_path / "latest.json").write_text(json.dumps(meta))

    ml_detector._loaded_model = None
    ml_detector._loaded_model_meta = None
    ml_detector.load_model_from_dir(str(tmp_path))
    assert ml_detector._loaded_model is not None

    w = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    score = ml_detector.score_prices(w, method="isolation")
    assert 0.0 <= score <= 1.0

    ml_detector._loaded_model = None
    ml_detector._loaded_model_meta = None


def test_load_model_missing_path(tmp_path):
    (tmp_path / "latest.json").write_text(json.dumps({"path": str(tmp_path / "missing")}))
    ml_detector.load_model_from_dir(str(tmp_path))


def test_load_model_invalid_metadata_is_logged_and_ignored(tmp_path):
    (tmp_path / "latest.json").write_text("not-json")
    ml_detector.load_model_from_dir(str(tmp_path))


def test_mad_and_isolation_failures_return_safe_score():
    with patch("services.analyzer.ml_detector.np.asarray", side_effect=ValueError("bad data")):
        assert ml_detector.score_prices(np.ones(5), method="mad") == 0.0

    with patch("services.analyzer.ml_detector.IsolationForest", side_effect=ValueError("model unavailable")):
        ml_detector._loaded_model = None
        assert ml_detector.score_prices(np.ones(5), method="isolation") == 0.0


@pytest.mark.asyncio
async def test_process_and_publish_if_deal():
    redis = AsyncMock()
    await ml_detector.process_and_publish_if_deal(
        redis, {"sku": "S", "store": "a", "price": 1, "timestamp": 1}, 0.9, threshold=0.8
    )
    redis.xadd.assert_awaited()

    redis.xadd.reset_mock()
    await ml_detector.process_and_publish_if_deal(
        redis, {"sku": "S"}, 0.1, threshold=0.8
    )
    redis.xadd.assert_not_awaited()

    redis.xadd.side_effect = Exception("fail")
    await ml_detector.process_and_publish_if_deal(redis, {"sku": "S"}, 0.99, 0.5)
