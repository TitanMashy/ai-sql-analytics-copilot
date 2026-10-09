# Capacity and load testing

This document explains what limits throughput, how to measure it, and how to size a deployment.
The measured results table is **empty until the load test has been run on your hardware**: capacity
depends on the database, the model's latency, and the data volume, and a number copied from another
environment would be wrong.

## What limits throughput

An `/ask` request has two phases with very different resource use:

| Phase | Duration | Holds |
|---|---|---|
| Generation (LLM call, repairs) | seconds | a provider worker thread and a request thread; **no database connection** |
| Execution (validate, then SQL) | milliseconds to seconds | one **analytics** connection, only while the query runs |

So the database connection pool is hit by the short phase and concurrency is limited mostly by
threads waiting on the model. Little's law gives the sizing rule: connections in use on average equal
the request rate times the average SQL time. With the default pool (5 + 10 overflow = 15 per process)
and 100 ms queries, one process can sustain about 150 executions per second before connections run
out; with 1-second queries, about 15. The LLM, not the pool, is usually the limit first: at an
average of 3 seconds per model call and the default 16 provider threads, one process completes about
5 LLM-backed requests per second, and `RATE_LIMIT_LLM_REQUESTS` (default 20 per principal per minute)
caps any single user well below that.

| Resource | Default | Saturates when |
|---|---|---|
| Analytics pool (per process) | 5 + 10 overflow | concurrent SQL executions exceed 15 -> `DATABASE_POOL_TIMEOUT` after 5 s |
| Provider threads (per process) | 16 | concurrent LLM calls exceed 16 -> requests queue and may hit the deadline |
| Request threads (per process) | 40 | concurrent in-flight requests exceed 40 |
| PostgreSQL `max_connections` | 100 (server default) | `replicas x 2 x 15` approaches it |
| Request deadline | 25 s | LLM time + repairs + SQL exceed it -> 504 |

## Running the load test

The scenario (`loadtest/ask.js`) posts the five mock-supported questions to
`POST /api/v1/analytics/ask`. The stack uses the mock provider with a simulated model latency
(`MOCK_LLM_LATENCY_MS` plus uniform `MOCK_LLM_JITTER_MS`; default 800 + up to 400 ms) so the
threading and pooling behavior is realistic without paying for tokens or being rate limited by a
provider.

```bash
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml up -d --build
docker compose --profile demo run --rm seed

# steady load at a fixed arrival rate; thresholds fail the run (exit 99)
k6 run -e BASE_URL=http://localhost:8000 -e RATE=10 -e DURATION=3m loadtest/ask.js

# ramp until something gives; records only (read loadtest-summary.json)
k6 run -e SCENARIO=saturation -e BASE_URL=http://localhost:8000 loadtest/ask.js
```

`steady` fails when more than 1 % of requests fail or p95 exceeds 2 s. A scheduled workflow
(`.github/workflows/loadtest.yml`) runs it weekly and uploads `loadtest-summary.json`.

**Recorded latency instead of assumed:** set `MOCK_LLM_LATENCY_MS` and `MOCK_LLM_JITTER_MS` to the
p50 and the spread of `analytics_llm_call_duration_seconds` from production, so the simulation
follows what you actually observe.

### Finding the saturation point

Watch these during the ramp (dashboard or `GET /api/v1/health/diagnostics`):

1. `ask_duration` p95 begins to climb faster than the request rate.
2. `analytics_sql_execution_errors_total{code="DATABASE_POOL_TIMEOUT"}` appears: the pool is the limit.
3. `analytics_deadline_exceeded_total` appears: threads or the (simulated) provider are the limit.
4. `http_req_failed` rises.

The arrival rate just before the first of these is the saturation point for that configuration.

## Measured results

Fill this in from your own runs. Record the commit, the hardware, the database size, and the
simulated latency, so a later run is comparable.

| Date | Commit | Backend (CPU / memory / replicas) | Pool | Simulated LLM latency | Rate at saturation | First limit hit | p95 at 50 % of saturation |
|---|---|---|---|---|---|---|---|
| _pending first run_ | | | | | | | |

## Recommended starting configuration

Until measured, start from these and adjust with the table above:

- **Replicas:** two, so one can be replaced while the other serves (`maxUnavailable: 0`).
- **Pools:** keep the defaults (5 + 10). Raise `DATABASE_POOL_SIZE` only if `DATABASE_POOL_TIMEOUT`
  appears at an arrival rate you intend to serve, and check the connection budget first:
  `replicas x 2 engines x (pool + overflow)` must stay under PostgreSQL's `max_connections`
  minus about 20 for migrations and administrators. Two replicas at defaults use 60.
- **Rate limits:** `RATE_LIMIT_LLM_REQUESTS` (default 20 per minute per principal) bounds model spend
  per user, per backend instance.
- **Statement budget:** `QUERY_TIMEOUT_SECONDS=10`, `QUERY_COST_LIMIT=1000000`, and
  `MAX_RESULT_ROWS=1000` together bound the work one question can cause.
- **Deadline:** `REQUEST_DEADLINE_SECONDS=25`, below the frontend's 30-second timeout.

## Rendering budget (frontend)

A result table renders at most 50 rows at a time (`PAGE_SIZE`), so a 1,000-row answer adds about 50
table rows to the page regardless of its size. The frontend unit test
(`frontend/components/analytics/analytics-results.test.tsx`) asserts that exactly 51 rows (header plus
one page) are in the DOM for a 1,000-row answer. Re-check the page in a browser profiler if the
table or chart components change.
