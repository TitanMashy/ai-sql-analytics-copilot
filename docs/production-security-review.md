# Production Security Review

## Scope and Threat Model

This review covers the current browser-to-API flow: Next.js dashboard, FastAPI request handling, Gemini or mock SQL generation, SQLGlot validation/repair, and PostgreSQL execution. The LLM and all request fields are treated as untrusted. Sprint 11 added authentication, tenant isolation, PII-free analytics views, a function allowlist, and a reduced public surface (see below). Shared multi-instance state, an identity provider, and cost-based query controls remain future work.

## Attack Surface

- Browser-reachable HTTP endpoints, limited by the frontend proxy to `ask`, conversations, schema tables, and health; authenticated API endpoints for schema, SQL generation, and (when enabled) direct SQL validation and execution; a token-protected metrics endpoint.
- Natural-language questions and caller-supplied conversation context passed to an external model when Gemini is enabled.
- Model-produced SQL, explanations, table names, and visualization metadata.
- Conversation session creation and append endpoints backed by in-memory state.
- PostgreSQL owner and read-only credentials supplied through runtime configuration.
- Docker Compose ports, health checks, logs, and the publicly reachable-by-default local metrics endpoint.

## Implemented Protections

| Area | Implemented protection |
|---|---|
| Configuration | Production mode disables debug and interactive API docs; provider keys use secret types; runtime values come from environment configuration. |
| Request limits | ASGI middleware bounds the complete buffered request body; Pydantic limits question, context, turn, SQL, and conversation-ID sizes. Validation responses are generic and request-correlated. |
| Authentication | Signed JWT bearer tokens (signature, expiry, issuer, audience, required claims, pinned algorithm) on every analytics and schema route; development modes are rejected in production. The principal carries the tenant. |
| Exposure | Frontend proxy allowlist; direct-SQL routes unmounted in production by default; metrics need a token; no published backend port in Compose; Next.js CSP, frame, and HSTS headers. |
| Abuse control | Rate limiting runs after authentication, keyed per principal (client IP only for unauthenticated development requests), on every route family with a stricter limit for LLM-backed calls; process-local, returns 429 with `Retry-After`. An overall request deadline stops slow providers and repair loops. |
| Data protection | `analytics_readonly` has no base-table privileges and reads only `analytics` views that omit personal data and filter rows to the caller's tenant (fail closed). Executions are read-only transactions with `SET LOCAL` timeouts. |
| Conversations | Owner-scoped (404 for others), user-only client turns, TTL and caps, failed attempts never stored. |
| CORS and headers | Exact CORS origins are configurable; responses set `nosniff`, frame, referrer, and permissions-policy headers. |
| Error handling | API errors use `{error: {code, message, request_id}}`; unexpected failures return a generic 500 without stack details. Provider and database logs record exception class/status only, not credentials, questions, or SQL. |
| Prompt/model | Question and history are bounded and labeled untrusted in the prompt. Gemini SDK calls have a timeout and three bounded exponential retries for transient 5xx responses; 429/quota, model-not-found, timeout, and malformed response failures are classified without unsafe retries. |
| SQL | SQLGlot validates every generated and repaired query: table and function allowlists, schema-qualifier and personal-data rules, join/nesting controls, normalization, an enforced outer `LIMIT`, PostgreSQL statement timeout, and a truncating row cap. Database errors are classified by SQLSTATE; repair receives a sanitized hint instead of the generic public message. Security, timeout, and provider failures do not trigger SQL repair/execution. |
| Database | Separate application-owner and analytics engines; configurable pool size/overflow/checkout/connect timeouts, pre-ping and recycle; connections are scoped and released. Compose initializes owner and read-only roles with distinct passwords for fresh databases. |
| Containers | Backend is non-root, runtime-only, read-only root filesystem, temporary `/tmp`, dropped capabilities and health checks. No keys are copied into Docker images. |
| Frontend | Same-origin proxy by default; no backend secrets in client variables; result/error payloads are runtime-checked; generated SQL and backend text are rendered as text; invalid chart metadata is dropped and chart failures are isolated. |

## Known Limitations

- Rate limiting and metrics are per process. Multi-instance deployments need a shared limiter at a gateway or shared store. `FORWARDED_ALLOW_IPS=*` in Compose is safe only because the backend is not published; narrow it if that changes.
- Metrics are process-local counters and averages protected by a single bearer token.
- The service validates tokens but has no identity provider, user directory, or token revocation. Tenant isolation is enforced by the analytics views from the transaction-local `app.scope`/`app.customer_id` settings; those are ordinary session settings, so the SQL validator's restrictions on `set_config`, `current_setting`, and `SET` are part of the boundary.
- Conversation sessions are in-memory and are lost on restart; caller-supplied context is bounded but not authenticated or persisted.
- PostgreSQL connection health does not prove Gemini account quota/model availability. Readiness checks provider configuration, not a remote generation call.
- The app has heuristic AST validation and timeout/row/complexity controls, not a cost-based planner or database `EXPLAIN` budget. PostgreSQL remains responsible for query planning.
- Compose is intended for local development. A production deployment needs private networking, TLS termination, ingress access control, secrets management, and database network restrictions. Secrets such as `JWT_SECRET` are plain environment variables today.
- For existing initialized PostgreSQL clusters, the initialization SQL does not rotate role passwords. Operators must explicitly alter the owner/read-only role passwords and update URLs before switching an existing cluster to password authentication.
- The API does not emit HSTS (TLS termination is deployment-specific); the Next.js app emits it in production builds. The CSP allows inline scripts because Next.js bootstrap scripts are inline; tighten it with nonces if that is acceptable for your deployment.
- Query-result caching is not implemented: there is no user/tenant scope or reliable data-change invalidation contract.

## Recommended Future Production Controls

1. Connect an identity provider that issues the expected token claims, and add token revocation if required.
2. Put TLS, request admission, and shared rate limiting at a maintained reverse proxy/API gateway.
3. Aggregate metrics and logs externally; protect the metrics endpoint and define retention/alerting.
4. Store conversation history durably with per-user ownership, retention, deletion, and audit rules.
5. Use a dedicated secret manager and credential rotation; do not rely on `.env` files in hosted environments.
6. Validate pool sizes, rate limits, timeout budgets, and row caps against representative production load and the database connection budget.
7. Add query-cost (`EXPLAIN`) budgets if the supported schema or threat model grows.
8. Tighten the CSP with nonces and enforce HSTS at the HTTPS gateway after validating Next.js asset requirements.

These recommendations are not implemented and must not be assumed to be present.
