# Runbook: database saturation or slow queries

**Alerts:** `AnalyticsAskAvailabilitySlowBurn`, `AnalyticsDatabaseSaturated`,
`AnalyticsQueryCostRejectionsHigh`.

## Symptoms

- `analytics_sql_execution_errors_total` rises with `code` `DATABASE_POOL_TIMEOUT`,
  `DATABASE_UNAVAILABLE`, or `QUERY_TIMEOUT`.
- `analytics_sql_execution_latency_seconds` p95 grows; `/ask` latency follows.
- Users see "The analytics database is busy" or "exceeded the configured timeout".
- `/health/ready` returns 503 when the databases are unreachable.

## Impact

Questions fail or are slow. The application database (conversations, audit) and the analytics
engine have separate pools, so a saturated analytics pool does not stop conversation history from
loading. No write path is exposed to analytics queries: the role is read-only and every query runs in a
read-only transaction, so saturation is an availability problem, not a data-integrity one.

## Diagnose

1. **Pool or database?** `GET /api/v1/health/diagnostics` (operator token) shows `pools` (checked-out
   and overflow connections per engine) and per-database `latency_ms`.
   - Pool exhausted but database idle: too many concurrent `/ask` requests for
     `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW` (default 15 per process). See
     [capacity.md](../capacity.md).
   - Database busy: look at PostgreSQL itself.
2. **What is running?** As a database administrator:
   ```sql
   SELECT pid, usename, state, now() - query_start AS running, left(query, 120)
   FROM pg_stat_activity
   WHERE usename = 'analytics_readonly' AND state <> 'idle'
   ORDER BY running DESC;
   ```
   Long-running statements are bounded by `statement_timeout` (`QUERY_TIMEOUT_SECONDS`, 10 s
   default), so anything much older than that points at a different workload on the same server.
3. **Expensive queries being generated?** `AnalyticsQueryCostRejectionsHigh` and
   `QUERY_COST_EXCEEDED` in `analytics_sql_execution_errors_total` mean the pre-flight is catching
   them. If that count is zero while timeouts rise, the limit may be too high for the data volume.
4. **One tenant or one principal?** The audit trail records the principal, tables, row count, and
   duration for every `/ask`:
   ```sql
   SELECT principal, count(*), avg(duration_ms), max(duration_ms)
   FROM audit_log WHERE occurred_at > now() - interval '1 hour' AND event = 'ask'
   GROUP BY principal ORDER BY avg(duration_ms) DESC LIMIT 10;
   ```

## Mitigate

- **Shed load:** lower `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_LLM_REQUESTS`, or block one principal at the
  gateway.
- **Stop runaway plans:** lower `QUERY_COST_LIMIT` (planner cost units) or `QUERY_TIMEOUT_SECONDS`;
  restart is required for settings changes.
- **Add capacity:** more backend replicas multiply connection demand; first raise the database's
  `max_connections` budget, then `DATABASE_POOL_SIZE`. Keep
  `replicas x (pool + overflow) x 2 engines` below the database limit.
- **Terminate a specific runaway session (last resort):**
  `SELECT pg_terminate_backend(<pid>);` as a superuser. The affected request fails with
  `DATABASE_UNAVAILABLE` and the user can retry.
- **Do not** grant the analytics role extra privileges or raise `statement_timeout` globally to make a
  report finish.

## Verify recovery

- No `DATABASE_POOL_TIMEOUT` or `QUERY_TIMEOUT` for 15 minutes.
- p95 SQL execution time is back to its baseline on the dashboard.
- `GET /health/ready` is 200, and `diagnostics` shows pool usage well below its limit.
- Smoke test passes.

## Follow-up

If saturation recurs, re-run the load test (`docs/capacity.md`) with current data volume and size the
pools and `QUERY_COST_LIMIT` from the result. Consider a read replica for the analytics engine
(`ANALYTICS_DATABASE_URL`).
