# Runbook: LLM provider outage or degradation

**Alerts:** `AnalyticsAskAvailabilityFastBurn`, `AnalyticsAskLatencyHigh`, `AnalyticsAnswerRateLow`,
`AnalyticsLlmErrorRatioHigh`, `AnalyticsDeadlineExceededFrequent`.

## Symptoms

- Users see "Too many requests", "The request took too long", or "I couldn't answer that".
- `analytics_llm_errors_total` rises, split by `code` (for example `LLM_TIMEOUT`,
  `LLM_RATE_LIMITED`, `LLM_PROVIDER_UNAVAILABLE`, `INVALID_LLM_RESPONSE`).
- `analytics_llm_call_duration_seconds` p95 climbs toward `LLM_TIMEOUT_SECONDS`.
- `/health/ready` returns `{"status": "degraded", "degraded": ["llm_provider"]}` only when the key is
  missing. A provider that is merely failing still reports ready, because readiness does not make a
  remote call.

## Impact

`/ask` and `/generate` fail or are slow. Everything that does not call the model keeps working:
conversation history, schema and definitions, feedback, and the dashboard shell. No SQL runs after a
provider failure, so there is no data risk. Questions already answered are not affected.

## Diagnose

1. **Which failure?** Group the error counter by code:
   `sum by (code) (rate(analytics_llm_errors_total[5m]))`.
   - `LLM_CONFIGURATION_ERROR`, `LLM_MODEL_UNAVAILABLE`: a credential or model-name problem, not an
     outage. Go to [credential-rotation.md](credential-rotation.md).
   - `LLM_RATE_LIMITED`: you are over the provider's quota. Check the provider console, and whether
     `AnalyticsRateLimitStorm` is also firing (one client can burn the quota).
   - `LLM_TIMEOUT` / `LLM_PROVIDER_UNAVAILABLE`: the provider is slow or down. Check its status page.
   - `INVALID_LLM_RESPONSE`: the model is returning malformed output. Look for a recent model or
     prompt change.
2. **Is it us or them?** Compare `analytics_llm_call_duration_seconds` with
   `analytics_sql_execution_latency_seconds`. If SQL is the slow part, use
   [database-saturation.md](database-saturation.md) instead.
3. **Request level:** find a failing request id in the user's error ("Reference: ...") or logs, and
   read its `http request completed` line: `llm_latency_ms`, `repair_count`, `status_code`.
4. **Retries multiply latency.** A request can spend up to `REQUEST_DEADLINE_SECONDS` (default 25)
   on generation plus up to `MAX_REPAIR_RETRIES` repairs; many repairs per request means the model is
   producing invalid SQL (`analytics_validation_rejections_total` by `reason`).

## Mitigate

- **Provider down:** nothing in this service can substitute a model. Tell users (banner or status
  channel) and wait; the service recovers by itself when the provider does.
- **Quota exhausted:** raise the provider quota or lower `RATE_LIMIT_LLM_REQUESTS` to shed load.
- **Provider slow, not down:** lower `LLM_TIMEOUT_SECONDS` so requests fail fast instead of tying up
  threads, and keep `REQUEST_DEADLINE_SECONDS` below the frontend timeout (30 s).
- **Bad model or prompt rollout:** roll back to the previous release tag (see
  [operations.md](../operations.md#rollback)) or set `GEMINI_MODEL` back to the previous model and
  restart.
- **Do not** raise `MAX_REPAIR_RETRIES` to compensate: it multiplies model load during an outage.

## Verify recovery

- `analytics:llm_error_ratio:rate5m` is below 5 % for 15 minutes.
- p95 `/ask` latency (`analytics:ask_latency_seconds:p95_5m`) is back under 15 s.
- The smoke test passes: `python scripts/smoke_test.py --base-url <url> --token <token>`.
- The evaluation subset passes: `python -m evals.run_eval --provider <mode> --subset mock` (mock) or
  the full suite against the real provider.

## Follow-up

Record the timeline and the provider's incident reference. If an outage repeated, consider a
second provider key in a different project or a lower `REQUEST_DEADLINE_SECONDS`.
