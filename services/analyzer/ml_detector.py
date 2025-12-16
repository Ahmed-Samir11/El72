from typing import Dict, Any
import logging
import asyncio
import numpy as np
from sklearn.ensemble import IsolationForest

from services.common.redis_client import RedisStreamClient

logger = logging.getLogger("analyzer.ml_detector")


def score_prices(window: np.ndarray, method: str = "mad", *, contamination: float = 0.05, random_state: int = 42) -> float:
    """Return an anomaly score in [0,1] for the latest sample in `window`.

    By default this function uses a fast, deterministic Median Absolute Deviation (MAD)
    based scorer which is suitable for the real-time hot path. Optionally, the
    `method='isolation'` will use sklearn's `IsolationForest` (much heavier).

    Parameters
    - `window`: 1-D numpy array ordered oldest->newest
    - `method`: 'mad' (default) or 'isolation'
    - `contamination`: used when `method=='isolation'`
    - `random_state`: RNG seed for the IsolationForest

    Returns a float between 0.0 (not anomalous) and 1.0 (highly anomalous).
    """
    if window is None or len(window) == 0:
        return 0.0

    # quick guard: insufficient data
    if len(window) < 5:
        return 0.0

    if method == "mad":
        # Median Absolute Deviation based score (fast and deterministic)
        try:
            x = np.asarray(window, dtype=float)
            median = np.median(x)
            mad = np.median(np.abs(x - median))
            if mad == 0:
                # fall back to small epsilon to avoid division by zero
                mad = np.mean(np.abs(x - median)) or 1.0
            latest = x[-1]
            # z-like score
            z = abs(latest - median) / mad
            # map z to [0,1] with soft thresholding (calibrate in prod)
            score = float(np.clip((np.tanh((z - 3.0) / 1.0) + 1.0) / 2.0, 0.0, 1.0))
            return score
        except Exception as e:
            logger.exception("MAD scorer failed: %s", e)
            return 0.0

    # fallback to IsolationForest (expensive)
    if method == "isolation":
        try:
            model = IsolationForest(contamination=contamination, random_state=random_state)
            model.fit(window.reshape(-1, 1))
            scores = model.decision_function(window.reshape(-1, 1))
            latest = scores[-1]
            norm = (np.tanh(-latest) + 1.0) / 2.0
            return float(np.clip(norm, 0.0, 1.0))
        except Exception as e:
            logger.exception("IsolationForest scoring failed: %s", e)
            return 0.0


async def score_prices_async(window: np.ndarray, method: str = "isolation", **kwargs) -> float:
    """Async wrapper that offloads the sync `score_prices` function to a threadpool.

    Use this when running heavy methods (e.g., `method='isolation'`) to avoid blocking
    the asyncio event loop.
    """
    return await asyncio.to_thread(score_prices, window, method, **kwargs)


async def process_and_publish_if_deal(redis_client: RedisStreamClient, event: Dict[str, Any], anomaly_score: float, threshold: float = 0.8) -> None:
    """If the score passes `threshold`, push event to confirmed deals stream.

    Caller must ensure DB writes and monetization logging are already done before calling.
    """
    try:
        if anomaly_score > threshold:
            payload = {
                "sku": event.get("sku"),
                "store": event.get("store"),
                "price": event.get("price"),
                "timestamp": event.get("timestamp"),
                "anomaly_score": anomaly_score,
            }
            # best-effort xadd; higher layers should handle failures if necessary
            await redis_client.xadd("stream:confirmed_deals", {"payload": payload})
    except Exception:
        logger.exception("Failed to publish confirmed deal for event: %s", event)
