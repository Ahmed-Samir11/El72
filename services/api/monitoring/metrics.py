from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

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


# Alert-event pipeline (plans/p2 MS1). The consumer runs inside this service,
# so its counters ride the same /metrics scrape as the HTTP metrics. The reason
# label is the consumer's own outcome set, which is what lets "no new alerts"
# be read as either "the market was quiet" or "the pipeline dropped it" —
# the distinction Gate 2 ("do users return?") is measured on.
ALERT_EVENTS_RECEIVED_TOTAL = Counter(
    "el72_alert_events_received_total",
    "Total stream:alerts messages read by the API alert-events consumer.",
)
ALERT_EVENTS_STORED_TOTAL = Counter(
    "el72_alert_events_stored_total",
    "Total alert_events rows written by the alert-events consumer.",
)
ALERT_EVENTS_SKIPPED_TOTAL = Counter(
    "el72_alert_events_skipped_total",
    "Total alert events skipped, labelled by outcome (duplicate, unknown_item, "
    "owner_mismatch, invalid, unsupported_event_type).",
    ["reason"],
)
ALERT_EVENTS_FAILED_TOTAL = Counter(
    "el72_alert_events_failed_total",
    "Total alert event messages that failed to write (transient DB failures "
    "and unexpected errors).",
)
ALERT_EVENTS_READ_ERRORS_TOTAL = Counter(
    "el72_alert_events_read_errors_total",
    "Total Redis XREADGROUP errors in the alert-events consumer. Named apart "
    "from write failures so \"the pipeline is down\" can never be confused with "
    "\"the events were unreadable\".",
)
ALERT_EVENTS_ACK_ERRORS_TOTAL = Counter(
    "el72_alert_events_ack_errors_total",
    "Total XACK failures: the entry stays pending and is re-decided, so this is "
    "the counter that explains growing consumer lag.",
)
ALERT_EVENTS_REDRAWS_TOTAL = Counter(
    "el72_alert_events_redraws_total",
    "Total deliveries of an entry that is still pending for this consumer "
    "(a retried failure, not a new event).",  # pending-reclaim pass
)
ALERT_EVENTS_DISCARDED_TOTAL = Counter(
    "el72_alert_events_discarded_total",
    "Total entries acked after MAX_DELIVERY_ATTEMPTS failed deliveries: bounded "
    "loss, made loud. \"No alerts\" must never silently mean \"we gave up\".",
)
ALERT_EVENTS_OPENED_TOTAL = Counter(
    "el72_alert_events_opened_total",
    "Total alert events whose opening was recorded by POST /alerts/{id}/open. Gate "
    "2 reads an opened/unopened ratio; counting the opens here means the ratio is "
    "visible to ops, not only inside the database.",
)
ALERT_EVENTS_ALREADY_OPEN_TOTAL = Counter(
    "el72_alert_events_already_open_total",
    "Total opens that found the event already opened (a re-tap of the same alert). "
    "Kept SEPARATE from the opened counter so refreshes cannot inflate the ratio.",
)
ALERT_EVENTS_EVENT_DELETED_TOTAL = Counter(
    "el72_alert_events_event_deleted_total",
    "Total opens where the event row was gone by the time of the write (an account "
    "or alert deleted mid-tap). Answered 404 rather than reporting an opening that "
    "was never recorded, and counted so a race is not invisible.",
)
ALERT_EVENTS_CLAIMED_TOTAL = Counter(
    "el72_alert_events_claimed_total",
    "Total entries re-owned with XAUTOCLAIM because they sat idle under a consumer "
    "name that no longer exists (a restarted replica). Without this pass those "
    "alerts are stranded in the group forever: not new, not ours.",
)
ALERT_EVENTS_CLAIM_ERRORS_TOTAL = Counter(
    "el72_alert_events_claim_errors_total",
    "Total XAUTOCLAIM failures. The stranded entries stay pending, so this counter "
    "is what distinguishes \"the market was quiet\" from \"we cannot reclaim\".",
)
ALERT_EVENTS_CONSUMER_UP = Gauge(
    "el72_alert_events_consumer_up",
    "1 while the alert-events consumer can read stream:alerts, 0 while it is "
    "backing off after a Redis failure. Dead-person guard: a stalled consumer "
    "otherwise looks exactly like a quiet market.",
)


def metrics_response():
    return generate_latest(), CONTENT_TYPE_LATEST
