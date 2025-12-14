from typing import Dict, Any
import numpy as np
from sklearn.ensemble import IsolationForest

from services.common.redis_client import RedisStreamClient


def score_prices(window: np.ndarray) -> float:
    """Return an anomaly score in [0,1] for the latest sample in `window`.

    This is a tiny example using IsolationForest. In prod, persist the model or use a rolling stateful approach.
    """
    if len(window) < 5:
        return 0.0
    model = IsolationForest(contamination=0.05)
    model.fit(window.reshape(-1, 1))
    scores = model.decision_function(window.reshape(-1, 1))
    # convert decision_function to 0..1 anomaly score (lower -> more anomalous)
    latest = scores[-1]
    # normalize roughly
    norm = (np.tanh(-latest) + 1) / 2
    return float(np.clip(norm, 0.0, 1.0))


async def process_and_publish_if_deal(redis_client: RedisStreamClient, event: Dict[str, Any], anomaly_score: float) -> None:
    """If the score passes threshold, push event to confirmed deals stream.

    Caller must ensure DB writes and monetization logging are already done before calling.
    """
    if anomaly_score > 0.8:
        payload = {
            "sku": event.get("sku"),
            "store": event.get("store"),
            "price": event.get("price"),
            "timestamp": event.get("timestamp"),
            "anomaly_score": anomaly_score,
        }
        await redis_client.xadd("stream:confirmed_deals", {"payload": payload})
