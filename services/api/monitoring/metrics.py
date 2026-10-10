from prometheus_client import Counter, Histogram, generate_latest
from prometheus_client import CONTENT_TYPE_LATEST


HTTP_REQUESTS_TOTAL = Counter(
    "el72_http_requests_total",
    "Total number of HTTP requests.",
    ["method", "endpoint", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "el72_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "endpoint"],
)


def metrics_response():
    return generate_latest(), CONTENT_TYPE_LATEST
