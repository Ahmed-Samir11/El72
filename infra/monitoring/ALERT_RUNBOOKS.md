# Analyzer Alert Runbooks

This file contains short runbooks for alerts defined in `prometheus_rules.yml`.

## AnalyzerDLQHigh (severity: critical)
Symptom: `analyzer_dlq_stream_length` > 10 for 5m.

Immediate checks:
- Query DLQ length: `redis-cli XLEN stream:dlq:analyzer`
- Check analyzer logs for parse or processing errors: `kubectl logs deploy/analyzer -c app --since=15m`
- Check Prometheus for related errors (e.g., publish failures)

Mitigation steps:
- If DLQ items are due to a parse/schema change, inspect a DLQ entry: `XRANGE stream:dlq:analyzer - + COUNT 1`
- Fix the downstream issue (parsing, model, DB) and replay DLQ items with a small script using `XADD stream:price_ingest` or a dedicated replay tool.
- If backlog is high, scale analyzer consumers (increase replicas) and ensure DB/Redis capacity.

Escalation:
- If DLQ keeps growing after fixes, page on-call and consider pausing producers until the root cause is resolved.

## AnalyzerDLQGrowingRate (severity: warning)
Symptom: DLQ received new items in last 5m.

Immediate checks:
- Inspect recent DLQ entries and error logs.
- Run a local replay of one DLQ item to validate fix.

Mitigation:
- Patch parsing or data handling quickly, then replay.

## AnalyzerConsumerLagHigh (severity: critical)
Symptom: `analyzer_consumer_pending` > 100 for 2m.

Immediate checks:
- Check consumer pod health: `kubectl get pods -l app=analyzer`
- Check pending entries: `redis-cli XPENDING stream:price_ingest cg_analyzer`
- Check DB connection pool usage and slow queries.

Mitigation:
- Scale analyzer replicas (HPA) or increase consumer_count and ensure each pod has unique consumer name.
- Increase DB pool size and monitor for saturated CPU/IO.
- Temporarily throttle producers or increase `publish_batch_size`/`publish_batch_interval_s`.

## AnalyzerPublishQueueHigh (severity: warning)
Symptom: `analyzer_publish_queue_size` > 50 for 2m.

Immediate checks:
- Check publisher task logs for errors.
- Inspect network/Redis connectivity and latency.

Mitigation:
- Restart publisher background task (rolling restart of analyzer pod).
- Increase `publish_batch_size` and/or `publish_retry_attempts` to reduce pressure.
- Ensure Redis has sufficient connections and CPU.

## AnalyzerDBPoolWaitersHigh (severity: warning)
Symptom: combined Postgres/Timescale pool waiters > 10 for 5m.

Immediate checks:
- Check DB slow queries and wait events in Postgres: run `SELECT pid, state, query, wait_event from pg_stat_activity WHERE state <> 'idle';`
- Check connection usage: `SELECT * FROM pg_stat_activity` and `pg_stat_database`

Mitigation:
- Increase `max_size` on asyncpg pools via environment variables.
- Optimize queries (add indexes) and reduce N+1 patterns.
- If DB is overwhelmed, consider throttling producers or scaling read replicas for heavy reads.

---

If you want, I can also add a simple `scripts/replay_dlq.py` helper and an automated Kubernetes Job manifest to replay DLQ items safely.

## AppEventsRejectionSpike (severity: warning)
Symptom: more than 20% of event rows received by `POST /events` were refused over 15m.

Immediate checks:
- Break the refusals down by reason: `sum by (reason) (rate(el72_events_rejected_total[15m]))`.
- `unknown_event`: a client build sends an event name outside the taxonomy in `services/api/events.py` (and the `app_events_event_allowlist` CHECK). Find the build that added it.
- `malformed`: rows carry an unexpected key or an id outside the opaque-token charset; compare the client's payload with `ALLOWED_KEYS`.
- `pii`: a client is putting a phone-shaped value into an event. Treat as a privacy bug in the app, not as noise.

Mitigation:
- Fix the client, or add the event to the taxonomy through a reviewed change to both `EVENT_TYPES` and the TimescaleDB CHECK (migration plus canonical schema).

## AppEventsStoreUnavailable (severity: warning)
Symptom: `POST /events` answered 503 (`reason="store_unavailable"`).

Immediate checks:
- Confirm `TIMESCALE_URL` is set for the api container and that TimescaleDB is reachable from it.

Mitigation:
- Restore the connection. The app drops batches it cannot send, so events from the outage window are lost, not delayed; note the window when reading funnel numbers.

## AppEventsSilent (severity: warning)
Symptom: no `app_events` rows stored for 6h, after a day that had traffic.

Immediate checks:
- Check whether requests reach the route at all: `el72_http_requests_total{endpoint="/events"}`.
- Check the latest app release for a disabled or broken analytics client.

Mitigation:
- Fix the client or the route. Like the outage case, the gap cannot be backfilled.

## app_events retention (no alert)
Rows older than the retention window are dropped by the TimescaleDB job created in `infra/sql/migrations/timescaledb/0003_app_events.sql` (`add_retention_policy`, 180 days pending the owner's decision in plans/p4 H9).

Checks:
- The policy exists: `SELECT * FROM timescaledb_information.jobs WHERE hypertable_name = 'app_events';`
- It runs: `SELECT * FROM timescaledb_information.job_stats WHERE hypertable_name = 'app_events';`
- Changing the window: `SELECT remove_retention_policy('app_events'); SELECT add_retention_policy('app_events', INTERVAL '<n> days');`, then update the migration, the canonical schema and the privacy policy together.

