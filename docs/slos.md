# Service level objectives

These are the targets the alerts and the Grafana dashboard are built around. They are starting
values chosen for an internal analytics product with an LLM in the request path; revisit them after
a few weeks of production data. Metrics come from `GET /api/v1/metrics/prometheus` (operator token);
the recording rules live in `ops/prometheus/slo-rules.yml`, the alerts in
`ops/prometheus/alerts.yml`, and the dashboard in `ops/grafana/dashboard.json`.

## Objectives

| # | Objective | Target | Window | Recording rule |
|---|---|---|---|---|
| 1 | **Availability** of `POST /api/v1/analytics/ask` | 99.5 % of requests do not fail with 5xx (including 504 deadline) | 30 days | `analytics:ask_availability:ratio_rate5m` (and `..._rate1h`) |
| 2 | **Latency** of `/ask` | p95 under 15 s, including the LLM call and repair attempts | 30 days | `analytics:ask_latency_seconds:p95_5m` |
| 3 | **Answer rate** (validator false-reject proxy) | at least 90 % of questions are not refused with 422 | 7 days | `analytics:ask_answer_rate:ratio_rate1h` |

### Why these three

- **Availability** counts only server-side failures. 4xx outcomes are the system working as
  designed: a rate-limited client, a question refused by the validator, or a request for data the
  caller may not see. Counting them would punish the service for protecting itself.
- **Latency** is end to end because that is what users feel. The LLM dominates it; the SQL part is
  tracked separately so a slow database is distinguishable from a slow model.
- **Answer rate** is the closest practical measure of **validator false rejections**. The validator
  cannot know that it rejected something that was actually safe, but a rise in questions ending
  in 422 (`QUERY_GENERATION_FAILED` after the repair loop) while the provider is healthy is how a bad
  allowlist, prompt, or model change shows up. The evaluation suite's `validation_failure_rate` and
  `execution_accuracy` are the pre-release version of the same signal. Malformed requests also return
  422, but they are rare from the dashboard.

## Error budget

99.5 % over 30 days allows about 3.6 hours of full unavailability, or the equivalent in partial
failures. Page when the budget burns fast (`AnalyticsAskAvailabilityFastBurn`: under 95 % over five
minutes and under 98 % over an hour); open a ticket when it burns slowly
(`AnalyticsAskAvailabilitySlowBurn`: under 99.5 % over an hour for an hour).

## What is deliberately not an objective

- **Correctness of answers.** It cannot be measured from traffic alone. It is covered by the
  evaluation suite (`docs/evaluation.md`) before release and by the helpful / not-helpful feedback
  counter (`analytics_feedback_by_rating_total`) after.
- **Per-tenant fairness.** Limits are per principal; there is no per-tenant SLO yet.

## Alert to runbook map

| Alert | Runbook |
|---|---|
| AnalyticsAskAvailabilityFastBurn, AnalyticsAskLatencyHigh, AnalyticsAnswerRateLow, AnalyticsLlmErrorRatioHigh, AnalyticsDeadlineExceededFrequent | [llm-provider-outage](runbooks/llm-provider-outage.md) |
| AnalyticsAskAvailabilitySlowBurn, AnalyticsDatabaseSaturated, AnalyticsQueryCostRejectionsHigh | [database-saturation](runbooks/database-saturation.md) |
| AnalyticsRateLimitStorm, AnalyticsRateLimiterBackendFailing | [rate-limit-storm](runbooks/rate-limit-storm.md) |
| AnalyticsSecurityRejectionsSpike, AnalyticsDatabasePermissionDenied | [suspected-data-leak](runbooks/suspected-data-leak.md) |
| AnalyticsLlmConfigurationError | [credential-rotation](runbooks/credential-rotation.md) |
| AnalyticsBackendDown | [operations: incident response](operations.md#incident-response) |

`backend/tests/test_ops_artifacts.py` fails if an alert uses a metric the application does not
export, links to a missing runbook, or a recording rule named here disappears.

## Tuning

Change a target by editing the recording rule or alert threshold, this document, and the dashboard
together. Do not tune an alert to silence a recurring page; either fix the cause or revisit the
objective on purpose.
