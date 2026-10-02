# Production Security Review

## Scope and Threat Model

This review covers the current browser-to-API flow: Next.js dashboard, FastAPI request handling, Gemini or mock SQL generation, SQLGlot validation/repair, and PostgreSQL execution. The LLM and all request fields are treated as untrusted. The application remains a portfolio MVP; it is not enterprise-grade or ready for anonymous, multi-tenant production traffic.

## Attack Surface

- Public HTTP endpoints for schema, health, metrics, SQL generation, validation, and analytics queries.
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
| Abuse control | Process-local sliding-window rate limiting returns HTTP 429 with `Retry-After` for generate, ask, conversation creation, and turn append requests. Limits are configurable. |
| CORS and headers | Exact CORS origins are configurable; responses set `nosniff`, frame, referrer, and permissions-policy headers. |
| Error handling | API errors use `{error: {code, message, request_id}}`; unexpected failures return a generic 500 without stack details. Provider and database logs record exception class/status only, not credentials, questions, or SQL. |
| Prompt/model | Question and history are bounded and labeled untrusted in the prompt. Gemini SDK calls have a timeout and three bounded exponential retries for transient 5xx responses; 429/quota, model-not-found, timeout, and malformed response failures are classified without unsafe retries. |
| SQL | SQLGlot validates every generated and repaired query. The allowlist, dangerous-operation/function checks, join/nesting controls, normalization, PostgreSQL statement timeout, and result row cap remain enforced. Security, timeout, and provider failures do not trigger SQL repair/execution. |
| Database | Separate application-owner and analytics engines; configurable pool size/overflow/checkout/connect timeouts, pre-ping and recycle; connections are scoped and released. Compose initializes owner and read-only roles with distinct passwords for fresh databases. |
| Containers | Backend is non-root, runtime-only, read-only root filesystem, temporary `/tmp`, dropped capabilities and health checks. No keys are copied into Docker images. |
| Frontend | Same-origin proxy by default; no backend secrets in client variables; result/error payloads are runtime-checked; generated SQL and backend text are rendered as text; invalid chart metadata is dropped and chart failures are isolated. |

## Known Limitations

- Rate limiting and metrics are per process, keyed by the direct ASGI client address. Behind a reverse proxy, all clients may share the proxy address unless a trusted ingress enforces client identity. Do not trust arbitrary `X-Forwarded-For` values. Multi-instance deployments need a shared limiter at a gateway or shared store.
- Metrics are process-local and unauthenticated. Restrict `/api/v1/metrics` to a trusted network or add authentication before exposing it publicly.
- There is no API authentication, authorization, user identity, tenant isolation, or row-level policy. The conversation ID is not an authorization credential.
- Conversation sessions are in-memory and are lost on restart; caller-supplied context is bounded but not authenticated or persisted.
- PostgreSQL connection health does not prove Gemini account quota/model availability. Readiness checks provider configuration, not a remote generation call.
- The app has heuristic AST validation and timeout/row/complexity controls, not a cost-based planner or database `EXPLAIN` budget. PostgreSQL remains responsible for query planning.
- The Compose port mappings are intended for local development. A production deployment needs private networking, TLS termination, ingress access control, secrets management, and database network restrictions.
- For existing initialized PostgreSQL clusters, the initialization SQL does not rotate role passwords. Operators must explicitly alter the owner/read-only role passwords and update URLs before switching an existing cluster to password authentication.
- HSTS is intentionally not emitted by the API because TLS termination is deployment-specific. Add it at the trusted HTTPS proxy.
- Query-result caching is not implemented: there is no user/tenant scope or reliable data-change invalidation contract.

## Recommended Future Production Controls

1. Add authentication, tenant-scoped authorization, and database row policies before exposing customer data.
2. Put TLS, request admission, trusted client-IP handling, and shared rate limiting at a maintained reverse proxy/API gateway.
3. Aggregate metrics and logs externally; protect the metrics endpoint and define retention/alerting.
4. Store conversation history durably with per-user ownership, retention, deletion, and audit rules.
5. Use a dedicated secret manager and credential rotation; do not rely on `.env` files in hosted environments.
6. Validate pool sizes, rate limits, timeout budgets, and row caps against representative production load and the database connection budget.
7. Consider database views, stricter tenant policies, and query-cost controls if the supported schema or threat model grows.
8. Add a deployment-specific CSP and HSTS at the HTTPS frontend/gateway after validating Next.js asset requirements.

These recommendations are not implemented and must not be assumed to be present.
