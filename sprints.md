# AI SQL Analytics Copilot: Production-Readiness Sprints

Sprints 1–10 (see [progress.md](progress.md)) delivered a working, production-oriented MVP. This plan adds **Sprint 11** and **Sprint 12**, which close the gaps found in the codebase audit and make the project production ready.

- **Sprint 11 — Secure and Correct:** close security exposure, make SQL generation/repair/execution correct, and fix the result-intelligence bugs. After this sprint the system is safe to expose to real users.
- **Sprint 12 — Reliable and Operable:** durable and shared state, a real-database test and quality pipeline, observability, frontend completeness, and a release process. After this sprint the system can be deployed, monitored, and maintained.

Each requirement has an ID, a description, and acceptance criteria (AC). A sprint is done only when every AC and the sprint's Definition of Done are met.

> **Implementation status.** Sprint 11 has been implemented in the codebase but **not yet executed**: no tests, linters, builds, migrations, or application runs were performed when it was written. Treat every Sprint 11 acceptance criterion as unverified until the backend suite (`make test`, `make lint`), the frontend suite, and the PostgreSQL integration tests (`tests/test_readonly_permissions.py`) pass. Deviations from the text below: tenant scoping (S11-09) is enforced in the `analytics` views instead of RLS policies, because the view owner bypasses RLS and the role must not read base tables; the sprint's frontend sign-in (S11-05) is a paste-a-token prompt, since no identity provider exists.

## Production-ready definition

The project is production ready when all of the following hold:

1. Every endpoint reachable from the internet is authenticated, rate limited per user, and either needed or disabled.
2. The database role can read only the data a user is allowed to see (no PII, no internal tables, tenant-scoped).
3. Generated SQL is validated by an allowlist, executed read-only with bounded time and rows, and failures are classified and repaired using useful information.
4. Conversation state, rate limiting, and metrics survive restarts and work across multiple instances.
5. CI runs against real PostgreSQL, includes a text-to-SQL accuracy evaluation, and gates merges.
6. Operators have dashboards-ready metrics, alertable errors, runbooks, and a documented release/rollback process.

---

# Sprint 11: Security Hardening and Correctness

**Goal:** Remove every known security exposure and fix defects that make answers wrong or unhelpful.

**Theme areas:** exposure and access control, database least privilege, SQL validation, execution and repair correctness, result intelligence.

## 11.1 Close the public attack surface

**S11-01 Narrow the frontend proxy**
- Replace the wildcard `/api/:path*` rewrite in `frontend/next.config.ts` with explicit routes the UI needs: `ask`, `conversations` (create/get/turns), `schema/tables`, and health.
- AC: `/api/v1/analytics/query`, `/api/v1/analytics/validate`, and `/api/v1/metrics` return 404 through the frontend origin. A test asserts this.

**S11-02 Gate internal endpoints**
- Add `ENABLE_DIRECT_SQL_ENDPOINTS` (default `false` in production). When disabled, `/query` and `/validate` are not mounted.
- Protect `/metrics` with a bearer token (`METRICS_TOKEN`) or bind it to an internal-only route.
- AC: in `APP_ENV=production` the direct-SQL routes are absent from the OpenAPI document and return 404; `/metrics` returns 401 without the token.

**S11-03 Stop publishing the backend port**
- In `docker-compose.yml`, remove the host `8000:8000` mapping from the default stack (keep it in a documented `docker-compose.dev.yml` override).
- AC: `docker compose up` exposes only the frontend on the host.

**S11-04 Frontend security headers**
- Add `headers()` to `next.config.ts`: `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security` (production).
- AC: a test or script asserts these headers on the page response; the dashboard loads with no CSP violations.

## 11.2 Authentication, authorization, and rate limiting

**S11-05 Authentication**
- Add an auth dependency for all `/api/v1/analytics/*` and `/api/v1/schema*` routes. Define a `Principal` (user id, tenant/customer id, roles). Provide two implementations behind one interface: a signed bearer token (JWT, issuer/audience/expiry validated) for real deployments, and a clearly labelled dev-only static token for local use that is rejected when `APP_ENV=production`.
- Unauthenticated requests return `401` using the existing error envelope.
- AC: all protected routes reject missing/invalid/expired tokens; production startup fails if the dev auth mode is configured; frontend sends credentials via the proxy and handles `401` with a clear sign-in-required state.

**S11-06 Per-principal, correctly-keyed rate limiting**
- Key the limiter on the authenticated principal, falling back to the real client IP. Run uvicorn with `--proxy-headers` and a configurable `FORWARDED_ALLOW_IPS`; never trust `X-Forwarded-For` from untrusted peers.
- Extend limits to every analytics route, and add a separate stricter limit on LLM-backed calls.
- AC: two users behind the same proxy IP have independent limits; a test proves one principal exhausting its quota does not affect another.

**S11-07 Conversation ownership**
- Bind each conversation to the creating principal. Reading or appending to another principal's conversation returns 404.
- Remove client-supplied `assistant`/`system` turn injection: the `/turns` endpoint accepts `user` turns only (or is removed if unused).
- AC: tests cover cross-principal access denial and rejected role injection.

## 11.3 Database least privilege and data protection

**S11-08 Analytics schema of views**
- Create an `analytics` schema containing views over the 11 allowed tables. Omit or mask PII (`users.email`, `drivers.phone`, `drivers.license_number`, and any other personal fields). Grant `analytics_readonly` `USAGE` on that schema and `SELECT` only on those views.
- Revoke the `ALTER DEFAULT PRIVILEGES ... GRANT SELECT` approach in `database/init/01-analytics-role.sql`; new tables must not become readable automatically.
- Update the validator, schema metadata, and prompts to reference the view surface.
- AC: `database/verify-readonly.sql` proves the role cannot read base tables, `alembic_version`, `seed_runs`, or any PII column, and cannot write. The migration creating the views is reversible.

**S11-09 Tenant isolation**
- Scope every analytics query to the principal's customer. Implement with PostgreSQL row-level security driven by a per-transaction setting (for example `SET LOCAL app.customer_id = <id>`) applied by the executor, and enforce that the setting is always set (queries fail closed when it is missing).
- AC: an integration test seeds two customers and proves a principal for customer A cannot see customer B rows through any generated or hand-written query, including joins, subqueries, and CTEs. Admin/global role behavior is explicit and tested.

**S11-10 Execution session hardening**
- Execute inside an explicit transaction using `SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`, `SET LOCAL lock_timeout`, and `SET LOCAL idle_in_transaction_session_timeout`, so no setting persists on pooled connections.
- Use `exec_driver_sql` (or equivalent) so `:name`-like text inside SQL literals is never treated as a bind parameter. Add tests for literals containing `:`, `%`, and `LIKE '%x%'`.
- AC: pooled connections carry no leftover session state; literal-colon and percent queries execute correctly.

## 11.4 SQL validator

**S11-11 Function allowlist**
- Replace the function denylist with an allowlist (aggregates, `date_trunc`, `extract`, `coalesce`, `nullif`, `round`, `abs`, `lower`, `upper`, `concat`, `cast`, window functions, and similar). Reject everything else, including any `pg_*`, `lo_*`, `dblink*`, `current_setting`, `set_config`, `version`, `inet_*`, `pg_sleep*` variants.
- AC: tests cover each rejected family and each allowed function; adding a function requires a conscious allowlist edit.

**S11-12 Schema-qualified and derived references**
- Reject any schema qualifier other than the analytics schema. Accept derived-table (subquery) aliases and lateral aliases as valid qualifiers so correct queries are not rejected.
- Derive `ALLOWED_TABLES` from schema metadata so the two cannot drift.
- AC: `foo.vehicles` and `pg_catalog.*` are rejected; `SELECT s.total FROM (SELECT ...) s` validates; a test fails if a metadata table is missing from the allowlist.

**S11-13 LIMIT enforcement**
- Rewrite the AST to enforce an outer `LIMIT max_rows + 1` when the query has none or has a larger/non-literal one. If the result exceeds `max_rows`, truncate and return a `truncated: true` flag and a warning instead of a hard error.
- AC: an unbounded query returns `max_rows` rows with `truncated: true`; the database never computes beyond `max_rows + 1` rows for plain selects; outer-versus-subquery `LIMIT` handling is tested.

## 11.5 Error classification and repair

**S11-14 SQLSTATE classification**
- Classify database errors by `SQLSTATE` (`42P01` undefined table, `42703` undefined column, `42883` undefined function, `42501` insufficient privilege, `57014` canceled, `22xxx` data exceptions), not by message substrings.
- AC: `column "x" does not exist` maps to a column error, not `TABLE_NOT_FOUND`; all existing error codes keep their HTTP statuses; tests exercise each SQLSTATE mapping.

**S11-15 Separate public message from repair hint**
- `AnalyticsServiceError` carries a public `message` and an internal `repair_hint` (sanitized: SQLSTATE class, primary message, offending identifier, never credentials or data values). Only the hint is sent to `repair_sql`.
- Pass the conversation context and the original provider-side schema context into repair for both providers.
- AC: a unit test shows an unknown-table and an unknown-column failure each produce a hint naming the identifier; the mock provider's repair uses the hint; the hint never appears in API responses.

**S11-16 Friendly terminal failure**
- When repair attempts are exhausted or the model repeatedly emits invalid SQL, return `422 QUERY_GENERATION_FAILED` with a user-safe message and request ID, not a raw validator message or `TABLE_NOT_FOUND`.
- AC: the frontend renders a clear "couldn't answer this question" state with a rephrase suggestion and optional "show SQL" for debugging in non-production.

**S11-17 Request deadline budget**
- Add an overall `REQUEST_DEADLINE_SECONDS` for `/ask` (default below the frontend timeout). Pass the remaining budget to provider calls and repair rounds; stop retrying when the budget is spent and return a `504`-class structured error.
- Reconcile Gemini's three internal retries with the budget. Align the frontend timeout so the browser never gives up before the server does.
- AC: a simulated slow provider test shows the server returns before the client timeout and does not continue work after the deadline.

## 11.6 Prompting and retrieval

**S11-18 Full-schema prompting and follow-up awareness**
- Include the full allowed schema in every prompt (11 small tables) and keep retrieval only for business-definition selection, or score retrieval using prior turns when the question has no keyword match. Remove the alphabetical fallback.
- Store the generated SQL and tables used with each assistant turn so follow-ups can build on the previous query. Do not store failed attempts as dangling user turns.
- AC: tests prove "and break that down by month?" after a revenue question generates SQL against the correct tables (verified with the mock provider and, in S12, the evaluation suite).

**S11-19 Prompt content and determinism**
- Add the current date/time and timezone, column enum values (from CHECK constraints), and the money/units conventions to the prompt. Move rules into a system instruction (Gemini `system_instruction`, OpenAI system role). Set temperature 0 for generation and repair.
- Move the shared repair-prompt construction into `SQLPromptBuilder` and delete the duplicated provider code. Pin the Gemini model to a specific version.
- AC: both providers build prompts through one code path; a snapshot test locks the prompt structure.

## 11.7 Result intelligence correctness

**S11-20 Structural KPI detection**
- Detect a KPI from shape (one row, one numeric non-identifier column) rather than keywords in the question.
- AC: "How many active vehicles do we have?" yields an `Active Vehicles` KPI; add that case to the tests alongside the existing ones.

**S11-21 Formatting from column semantics**
- Derive `currency`/`percentage`/`integer` from the column name and type only, never from the question text. Fix substring false positives (for example `rate` inside `generated`).
- AC: "Top 10 customers by revenue" formats the count column as integer and the revenue column as currency; regression tests cover the false positives.

**S11-22 Visualization and summary quality**
- Support multiple numeric series where sensible. Restrict pie charts to additive measures with at most 6 categories. Never reuse a colour within a chart. Sort time series by the x field. Emit a short chart title, not the whole question.
- Summaries respect sort direction and the question ("lowest", "bottom") and format values with the column format. Remove or wire the unused `gemini_summary` hook.
- AC: tests cover ascending versus descending summaries, multi-series fuel results, and a 6-category pie.

## 11.8 Sprint 11 Definition of Done

- All S11 requirements met; every acceptance criterion backed by an automated test.
- A security re-review against `docs/production-security-review.md`, updating the document with the new controls and removing resolved "recommended" items.
- `docs/security.md`, `docs/architecture.md`, `docs/deployment.md`, and `.env.example` updated for new settings (auth, deadline, proxy headers, endpoint gates, metrics token).
- Backend `ruff` and `pytest` and frontend lint, test, and build all pass.
- No critical or high finding from the audit remains open.

## 11.9 Sprint 11 risks

- Views plus RLS change the schema surface the LLM sees: update prompts and the validator together and re-check mock answers.
- Auth introduces a frontend sign-in flow; if no identity provider is available, deliver the JWT interface plus a documented local-issuer script and defer the provider choice.

---

# Sprint 12: Reliability, Quality Gates, and Operations

**Goal:** Make the system reliable at more than one instance, provably accurate and regression-safe, observable, complete on the frontend, and releasable.

**Theme areas:** durable shared state, CI and evaluation, observability, frontend completeness, performance, delivery and operations.

## 12.1 Durable and shared state

**S12-01 Durable conversations**
- Store conversations and turns in PostgreSQL (new Alembic migration) with `principal_id`, timestamps, and a retention policy (`CONVERSATION_TTL_DAYS`, scheduled cleanup). Keep the `ConversationMemory` interface; add a SQL-backed implementation and make the in-memory one the test double. Include the SQL and tables used per assistant turn.
- Cap sessions and turns per principal.
- AC: a backend restart or a second replica continues an existing conversation; ownership checks from S11-07 still apply; expired conversations are purged by a documented job.

**S12-02 Shared rate limiter**
- Introduce a `RateLimiter` interface with the existing in-process implementation and a Redis-backed implementation (sliding window or token bucket). Selected by `RATE_LIMIT_BACKEND`. Add Redis to Compose as an optional profile and to the readiness check when selected.
- AC: with two backend replicas and Redis, the combined limit is honored (integration test); with Redis down, behavior is configurable (`fail-open` or `fail-closed`) and documented.

**S12-03 Prompt-to-SQL cache (optional, flagged)**
- Cache validated SQL keyed by normalized question, schema version, and tenant, with a short TTL. Never cache result rows across tenants.
- AC: disabled by default; when enabled, repeat questions skip the LLM call and a metric records the hit ratio.

## 12.2 Testing and quality gates

**S12-04 PostgreSQL in CI**
- Add a `postgres:16` service container to the backend CI job. Run the init script, migrations, and seed; run all `integration` tests (read-only permissions, RLS isolation, statement timeout, view privileges).
- AC: CI fails if any integration test is skipped for lack of credentials; the permission and tenant isolation tests run on every push.

**S12-05 Text-to-SQL evaluation suite**
- Create a golden dataset of at least 50 questions (including follow-ups, ambiguous phrasing, and adversarial prompts such as injection attempts and requests for PII) with expected result sets or expected structural properties. Provide a runner that executes against seeded PostgreSQL with a configurable provider and reports execution accuracy, validation-failure rate, repair rate, p50/p95 latency, and token cost.
- Run it nightly and on demand in CI with a real provider key (secrets-gated); run a deterministic subset on every push with the mock provider.
- AC: thresholds are defined and enforced (for example execution accuracy and a zero-leak requirement on adversarial cases); results are published as a CI artifact and trended.

**S12-06 Static analysis and supply chain**
- Add `mypy` (or `pyright`) for the backend, `ruff format --check`, `pip-audit`, `npm audit --omit=dev`, and a lockfile for backend dependencies. Add Dependabot or Renovate. Build both Docker images in CI and scan them (for example Trivy).
- AC: CI fails on new type errors, high-severity vulnerabilities, or an image build failure.

**S12-07 Test depth**
- Add backend coverage reporting with a minimum threshold on `app/analytics`, `app/services`, and `app/llm`. Add property/fuzz tests for the validator (randomized SQL and mutation of known-bad queries). Add frontend component tests for the result-per-message UI and a Playwright end-to-end test of the full path (sign in, ask, chart, follow-up, error states) against the Compose stack in mock mode.
- AC: coverage thresholds enforced; the fuzz suite runs in CI with a fixed seed and a longer scheduled run; the end-to-end test runs in CI.

## 12.3 Observability

**S12-08 Metrics and tracing**
- Replace the average-only metrics with Prometheus-format histograms and counters (request duration by route and status, LLM latency and errors by provider, validation failures by reason, SQL execution time, repair attempts and success, rate-limit rejections, cache hit ratio, active conversations). Add OpenTelemetry tracing across request, LLM call, validation, and execution with the request ID as the trace attribute. Make the exporter configurable.
- AC: `/metrics` serves Prometheus text format (token-protected); a sample trace shows spans for each pipeline stage; cardinality is bounded (no question text or SQL as labels).

**S12-09 Logging and audit trail**
- Keep logs free of questions, SQL, and secrets. Add an audit log (separate sink or table) of principal, conversation id, request id, a hash of the SQL, tables touched, row count, duration, and outcome, so access can be reviewed without storing content.
- AC: an audit record exists for every `/ask`; a test proves logs and audit records contain no question text, SQL text, or credentials.

**S12-10 Alerts, SLOs, and runbooks**
- Define SLOs (availability, p95 `/ask` latency, SQL-validation false-reject rate) and ship example alert rules and a Grafana dashboard JSON. Write runbooks in `docs/runbooks/` for: LLM provider outage, database saturation, rate-limit storm, suspected data leak, credential rotation.
- AC: each alert references a runbook; the runbooks are reviewed through a tabletop exercise noted in the sprint review.

**S12-11 Health semantics**
- Split liveness (process up) from readiness (dependencies reachable, configuration valid) and from a deep diagnostic route available to operators only. Do not mark a container unhealthy because an optional dependency or provider is degraded; report degraded state instead.
- AC: killing Redis or the LLM key produces a `degraded` readiness body with the correct HTTP status per documented policy; Compose and Kubernetes probe examples are provided.

## 12.4 Frontend completeness

**S12-12 Result per message**
- Keep each result with its assistant message and render it inline, so earlier charts and tables remain visible after follow-ups. Persist the visible thread via the durable conversation API on reload.
- AC: component tests show multiple results in a thread; reloading the page restores the conversation.

**S12-13 Chart and table polish**
- Add legends and labels, readable date axes (format ISO timestamps by granularity), multi-series support from S11-22, a consistent categorical palette that never repeats, and keyboard/screen-reader access to charts (data table fallback and `aria` labels). Add a truncation notice using the `truncated` flag. Virtualize or paginate large tables. Add CSV export of the visible result.
- AC: automated accessibility checks (axe) pass on the dashboard; a 1000-row result renders without layout jank (measured budget documented).

**S12-14 Typed contract and cleanup**
- Generate frontend types from the backend OpenAPI schema (or share a single schema), and replace the hand-written `normalizeAskResponse` with schema validation. Remove dead code (`deleteConversation`, unreachable empty-state markup, redundant row-count text) or implement the backend `DELETE` route and use it.
- AC: CI fails if the generated types are stale; a backend contract change breaks the frontend build.

**S12-15 UX states**
- Handle `401`, `429` (with `Retry-After` countdown), `504`, and `QUERY_GENERATION_FAILED` distinctly; add example questions and a short "what can I ask" panel from the business definitions; add feedback buttons (helpful/not helpful) recorded via the audit trail.
- AC: each error state has a component test and copy reviewed for clarity.

## 12.5 Performance and capacity

**S12-16 Load and capacity test**
- Add a k6 (or Locust) scenario for `/ask` with the mock provider and a recorded-latency provider simulation. Document capacity for the default pool sizes, the point at which the pool saturates, and a recommended replica and pool configuration.
- Add `EXPLAIN`-based pre-flight cost estimation: reject plans above a configurable cost threshold before execution (`QUERY_COST_LIMIT`).
- AC: the load test runs in a scheduled job and reports p95 latency and error rate; an expensive cross-join-like query is rejected pre-execution in an integration test.

## 12.6 Delivery and operations

**S12-17 Release pipeline**
- Tag-driven release workflow: build, test, scan, push images to a registry with immutable version tags and SBOM, and generate release notes from conventional commits. Add environment promotion (staging then production) with a smoke test (`/health/ready` plus one authenticated `/ask`).
- AC: a tagged release produces versioned images and a changelog; the smoke test gates promotion; rollback to the previous tag is documented and rehearsed.

**S12-18 Migrations and data operations**
- Run migrations as a dedicated one-shot job, not at app start. Document expand/contract migration practice and backward-compatible deploys. Document and test backup and restore of PostgreSQL, and add a seed/demo-data separation so production never loads demo data.
- AC: a restore drill is recorded; the production profile cannot run the demo seed.

**S12-19 Secrets and configuration**
- Support loading secrets from a secret manager or mounted files (`*_FILE` variants) rather than plain environment variables, with rotation documented for both database roles, the LLM key, JWT keys, and the metrics token. Validate the complete production configuration at startup and fail with a precise message.
- AC: the app starts with `*_FILE` secrets; rotation steps are verified in a rehearsal; misconfiguration produces a clear startup error.

**S12-20 Documentation and handoff**
- Update `README.md`, `docs/architecture.md`, `docs/deployment.md`, and `progress.md` to reflect Sprints 11–12 (remove the now-obsolete Known Limitations and Future Improvements items). Add `docs/operations.md` (deploy, scale, rotate, back up, respond), `docs/evaluation.md` (how to run and interpret the suite), and a short threat model.
- AC: a new engineer can deploy to a clean environment, run evaluation, and follow a runbook using only the docs (validated by a fresh-environment walkthrough).

## 12.7 Sprint 12 Definition of Done

- All S12 requirements met; every acceptance criterion backed by an automated test, CI job, or recorded drill.
- CI is green on pull requests with PostgreSQL, evaluation subset, type checks, audits, image builds, and end-to-end tests; the nightly evaluation and load jobs are scheduled and passing against agreed thresholds.
- The multi-replica deployment (two backend instances, Redis, PostgreSQL) is exercised in staging, including a rolling restart with no lost conversations.
- Dashboards, alerts, and runbooks are in place and have been reviewed.
- `progress.md` marks Sprints 11–12 complete and lists any consciously deferred items with owners.

## 12.8 Sprint 12 risks

- Evaluation thresholds depend on the chosen model and may need tuning after the first baseline run; record the baseline before enforcing gates.
- Redis and tracing add operational components; keep both optional behind configuration, with in-process fallbacks documented for single-instance deployments.

---

# Cross-sprint summary

| Area | Sprint 11 | Sprint 12 |
|---|---|---|
| Exposure and access | Proxy allowlist, endpoint gating, auth, per-principal limits, conversation ownership | Shared rate limiter, secrets management |
| Data protection | Analytics views, PII removal, RLS tenant isolation, read-only transaction settings | Audit trail, backup/restore |
| SQL pipeline | Function allowlist, qualifier and alias fixes, LIMIT enforcement, SQLSTATE and repair hints, deadline budget, prompt and retrieval fixes | Evaluation suite, cost pre-flight, optional SQL cache |
| Result intelligence | Structural KPI, correct formatting, chart and summary fixes | Accessible and polished charts, CSV, truncation UX |
| State | Conversation ownership | Durable conversations, shared limiter |
| Quality | Unit and integration tests for every fix | Postgres CI, fuzzing, coverage, type checking, end-to-end tests, supply-chain scans |
| Operations | Updated security docs | Metrics and tracing, SLOs, alerts, runbooks, release pipeline, load testing, migration job, documentation |

## Out of scope for both sprints

- Write operations, data modification, or any non-SELECT capability.
- Multiple database engines or non-PostgreSQL analytics sources.
- Fine-tuning or hosting your own LLM.
- A full multi-tenant admin console or billing for the product itself.
