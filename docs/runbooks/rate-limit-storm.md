# Runbook: rate-limit storm

**Alert:** `AnalyticsRateLimitStorm`.

## Symptoms

- `analytics_rate_limit_rejections_total` is high, split by `scope` (`llm`, `read`, `conversation`,
  `direct`). Users see HTTP 429 and "Try again in N s".

## Impact

- The offending client is throttled; others are unaffected because limits are per authenticated
  principal (and per client address only for unauthenticated development traffic).
- Counters live in the backend process, so a restart clears them and each instance enforces its own
  limit.

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

## Mitigate

- **Abusive principal:** revoke or rotate that principal's credentials at the identity provider, or
  block it at the gateway. Do not raise limits to make the alert quiet.
- **Limits too low for real demand:** raise `RATE_LIMIT_REQUESTS` or `RATE_LIMIT_LLM_REQUESTS` (the LLM
  limit is the one that protects model spend) and restart.
- **Do not** disable rate limiting (`RATE_LIMIT_ENABLED=false`) in production.

## Verify recovery

- `analytics_rate_limit_rejections_total` returns to its normal trickle.

## Follow-up

Add the offending client to your abuse list and review whether per-principal limits need different
tiers.
