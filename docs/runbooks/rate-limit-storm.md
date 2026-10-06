# Runbook: rate-limit storm or rate-limiter backend failure

**Alerts:** `AnalyticsRateLimitStorm`, `AnalyticsRateLimiterBackendFailing`.

## Symptoms

- `analytics_rate_limit_rejections_total` is high, split by `scope` (`llm`, `read`, `conversation`,
  `direct`). Users see HTTP 429 and "Try again in N s".
- Or: `analytics_rate_limiter_failures_total` increases, and `/health/ready` reports
  `{"status": "degraded", "degraded": ["rate_limiter"]}` (fail-open) or returns 503 (fail-closed).

## Impact

- **Storm:** the offending client is throttled; others are unaffected because limits are per
  authenticated principal (and per client address only for unauthenticated development traffic).
- **Redis down, `RATE_LIMIT_FAIL_MODE=open`:** requests are admitted without limits. The service
  stays available, but abuse protection and LLM spend control are off until Redis returns.
- **Redis down, `closed`:** requests that need the limiter fail with 503 `DEPENDENCY_UNAVAILABLE`.

## Diagnose

1. **Is it one principal?** The audit trail shows who is asking:
   ```sql
   SELECT principal, count(*) AS asks
   FROM audit_log WHERE occurred_at > now() - interval '15 minutes' AND event = 'ask'
   GROUP BY principal ORDER BY asks DESC LIMIT 10;
   ```
   A single principal sending hundreds per minute is a script or an abuse; many principals all
   rejected at once means limits are too low for the legitimate load.
2. **Behind a proxy?** Unauthenticated development deployments key on client IP. If every user
   shares one address (the proxy's), they share one bucket: check `FORWARDED_ALLOW_IPS` and that
   the proxy sets `X-Forwarded-For`.
3. **Redis:** `redis-cli -u "$REDIS_URL" ping`; check memory, connections, and whether the keys with
   prefix `analytics:ratelimit:` are expiring (each has a TTL equal to the window).
4. `GET /api/v1/health/diagnostics` shows the rate-limit backend, its latency, and the fail mode.

## Mitigate

- **Abusive principal:** revoke or rotate that principal's credentials at the identity provider, or
  block it at the gateway. Do not raise limits to make the alert quiet.
- **Limits too low for real demand:** raise `RATE_LIMIT_REQUESTS` or `RATE_LIMIT_LLM_REQUESTS` (the LLM
  limit is the one that protects model spend) and restart.
- **Redis down:** restore it (restart, failover, or fix networking). While it is down decide
  deliberately: stay fail-open for availability (and watch LLM spend), or switch to
  `RATE_LIMIT_FAIL_MODE=closed` and accept 503s. Setting `RATE_LIMIT_BACKEND=memory` as a stop-gap
  makes each replica enforce its own limit, so the effective limit is `replicas x limit`.
- **Do not** disable rate limiting (`RATE_LIMIT_ENABLED=false`) in production.

## Verify recovery

- `analytics_rate_limit_rejections_total` returns to its normal trickle.
- `analytics_rate_limiter_failures_total` stops increasing; readiness is plain `ready`.
- With two replicas, send requests above the limit and confirm the combined limit is enforced
  (`tests/test_redis_limiter.py`, integration, shows the expected behavior).

## Follow-up

Add the offending client to your abuse list, review whether per-principal limits need different
tiers, and size Redis for the key count (principals x scopes).
