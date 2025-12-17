import asyncio

import numpy as np

from services.analyzer import ml_detector


def test_score_prices_mad_small_window():
    w = np.array([100.0, 101.0, 99.5, 100.2])
    # small window -> below minimum returns 0
    assert ml_detector.score_prices(w[:4]) == 0.0


def test_score_prices_mad_basic():
    w = np.array([100.0, 100.0, 100.0, 100.0, 150.0])
    s = ml_detector.score_prices(w, method="mad")
    assert 0.0 <= s <= 1.0
    assert s > 0.0


def test_score_prices_async_matches_sync():
    w = np.linspace(100.0, 110.0, num=20)
    sync = ml_detector.score_prices(w, method="mad")
    async_score = asyncio.run(ml_detector.score_prices_async(w, method="mad"))
    assert abs(sync - async_score) < 1e-6


def test_score_prices_isolation_forest():
    w = np.array([100.0, 101.0, 99.5, 100.2, 200.0])
    s = ml_detector.score_prices(w, method="isolation")
    assert 0.0 <= s <= 1.0


def test_load_model_from_dir_no_file():
    # Test loading when no model file exists
    ml_detector.load_model_from_dir("nonexistent")
    assert ml_detector._loaded_model is None
