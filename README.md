# AI SQL Analytics Copilot

The AI SQL Analytics Copilot turns natural-language fleet questions into safe, explainable SQL workflows. Its Next.js dashboard presents backend-validated results as conversations, KPIs, charts, tables, and generated SQL.

## Architecture

The system is a modular monolith: Next.js presentation layer -> FastAPI -> schema/business context -> model provider (mock, Gemini or Ollama, through LangChain) -> SQLGlot validation -> PostgreSQL read-only execution -> result intelligence. SQL generation, validation, metric definitions, summaries, and visualization selection remain backend-owned.

End-to-end, a request is authenticated (signed bearer token) and rate limited per principal; a question is length-validated and assigned a request ID; schema and business definitions are retrieved; the selected provider returns structured SQL; `/generate` returns that SQL without execution, while `/ask` sends it through AST validation, bounded repair when a classified error is repairable, and the read-only query service. Successful rows then receive KPI, visualization, warning, and grounded summary metadata for the frontend. No provider-generated SQL bypasses validation.

Documentation index: [docs/README.md](docs/README.md). Model providers (mock, Gemini, Ollama, tracing): [docs/llm-providers.md](docs/llm-providers.md). See also [docs/architecture.md](docs/architecture.md), [docs/database-schema.md](docs/database-schema.md), [docs/business-definitions.md](docs/business-definitions.md), [docs/deployment.md](docs/deployment.md), [docs/operations.md](docs/operations.md) (deploy, scale, rotate, back up, release, roll back, respond), [docs/evaluation.md](docs/evaluation.md), [docs/slos.md](docs/slos.md), [docs/capacity.md](docs/capacity.md), [docs/threat-model.md](docs/threat-model.md), and [docs/production-security-review.md](docs/production-security-review.md).

## Stack

- Python 3.12+, FastAPI, Pydantic, SQLAlchemy, psycopg, SQLGlot, Alembic
- PostgreSQL 16, LangChain model integrations (Gemini, Ollama), deterministic mock provider
- Next.js 16, React 19, TypeScript, Tailwind CSS, Recharts, Vitest
- Docker Compose, pytest, Ruff, GitHub Actions

## Local Development

Backend virtual environment and dependencies:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On Windows, keep the project in a short path (for example `C:\src\...`) or enable long paths: a dependency of the model integrations (`google-genai`) has very long file names, and `pip install` fails with `WinError 206` when the virtual environment is nested deeply.

Without `.env`, the backend uses local SQLite defaults and `AUTH_MODE=disabled` (a development-only mode that production rejects). Start it with `make dev`; the API is at http://localhost:8000. `GET /health` is liveness, `GET /health/ready` checks required databases/provider configuration, and development API docs are at `/docs`.

To use a configured PostgreSQL database, run `make migrate` and `make seed`. Seeding is deterministic and idempotent.

Run the frontend separately:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Next.js proxies only the routes the dashboard uses (`ask`, conversations, schema tables, health) to `http://localhost:8000`, keeping browser calls same-origin; direct-SQL, SQL-validation, SQL-generation, and metrics routes are not reachable through it. `INTERNAL_API_URL` is applied when `next build` evaluates the proxy rewrites. The browser receives no provider or database credentials. With `AUTH_MODE=jwt` the dashboard asks for an access token (`python backend/scripts/issue_token.py --customer-id 7` issues one for local testing).

## APIs and Security

- `POST /api/v1/analytics/generate` generates SQL without executing it.
- `POST /api/v1/analytics/ask` generates, validates, executes, and returns result intelligence.
- `POST /api/v1/analytics/query` and `/validate` expose the internal direct-SQL surface. They are not mounted in production unless `ENABLE_DIRECT_SQL_ENDPOINTS=true`.
- `GET /api/v1/metrics` returns process-local counters and latency averages; it needs `METRICS_TOKEN` when set and is disabled in production when unset.
- Every analytics and schema route needs `Authorization: Bearer <token>` (outside `AUTH_MODE=disabled`); health endpoints are open.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe: the process is up; touches no dependency. |
| GET | `/health/ready` | Readiness: 503 when a required dependency is down; 200 with `{"status": "degraded", "degraded": [...]}` when something optional is (missing LLM key). |
| GET | `/api/v1/health/diagnostics` | Operator-only: dependency latency, pool state, migration revision, enabled features. Needs `METRICS_TOKEN`. |
| GET | `/api/v1/health` | Compatibility application-database health check. |
| GET | `/api/v1/health/ready` | Versioned readiness alias. |
| GET | `/api/v1/metrics` | Process-local counters and average latencies (JSON). Bearer `METRICS_TOKEN`; disabled in production when unset. |
| GET | `/api/v1/metrics/prometheus` | The same counters plus labelled histograms in Prometheus text format. Same token. |
| POST | `/api/v1/analytics/generate` | Generate structured SQL without execution. |
| POST | `/api/v1/analytics/ask` | Generate, validate, execute, and analyze results. Accepts optional `conversation_id` and bounded `conversation_context`. |
| POST | `/api/v1/analytics/query` | Validate and execute one direct read-only SQL statement (gated; see above). |
| POST | `/api/v1/analytics/validate` | Validate SQL without executing it (gated; see above). |
| POST | `/api/v1/analytics/conversations` | Create a conversation owned by the caller. |
| GET | `/api/v1/analytics/conversations/{conversation_id}` | Read your own conversation (404 for anyone else's). |
| DELETE | `/api/v1/analytics/conversations/{conversation_id}` | Delete your conversation and its history. |
| POST | `/api/v1/analytics/conversations/{conversation_id}/turns` | Append a bounded user turn to your own conversation. |
| POST | `/api/v1/analytics/feedback` | Record whether an answer was helpful (request id + rating; no free text). |
| GET | `/api/v1/schema`, `/api/v1/schema/tables`, `/api/v1/schema/tables/{table_name}` | Read schema metadata. |
| GET | `/api/v1/schema/business-definitions` | Metric definitions and example questions. |
| GET | `/docs` | Interactive API documentation outside production mode. |

Errors use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }` (outside production, `QUERY_GENERATION_FAILED` also carries `error.debug.sql`). Requests are size- and length-limited; every analytics, conversation, and schema route has configurable per-principal rate limits, with a stricter limit on LLM-backed calls, and each question has an overall time budget (`REQUEST_DEADLINE_SECONDS`). PostgreSQL statement timeout, an enforced outer `LIMIT` (results over `MAX_RESULT_ROWS` are truncated and flagged), table/column/function allowlists, and AST validation remain enforced for generated and repaired SQL. Generated SQL is always untrusted.

The analytics DB uses a separate `analytics_readonly` role with a distinct password. It has no privileges on the application tables; it reads PII-free, tenant-scoped views in the `analytics` schema inside read-only transactions, and each query is limited to the authenticated principal's customer (`analytics_admin` sees all). Do not grant it writes or use application-owner credentials for analytics execution. See [docs/security.md](docs/security.md) for SQL controls and [docs/production-security-review.md](docs/production-security-review.md) for implemented controls versus recommended future controls. AST validation is defense in depth, not a complete security guarantee.

Choose the model explicitly with `LLM_PROVIDER` (`mock`, `gemini` or `ollama`) and `LLM_MODEL`; Gemini also needs `GEMINI_API_KEY`. Mock mode requires no key, is deterministic, and is disabled in production. There is no fallback between providers: if the selected one is down the request fails with a classified error. Generated SQL is never executed after a provider failure, and SQL from every provider is validated the same way. Optional LangSmith tracing (`LANGSMITH_TRACING`, off by default) records only allowlisted metadata, never questions, SQL or rows. `python scripts/llm_smoke.py` checks the configured provider end to end. Setup for each provider, including Ollama on macOS and Docker networking, is in [docs/llm-providers.md](docs/llm-providers.md).

### Switching the model provider

Selection is explicit, in `.env` (Compose) or the environment (running directly). There is no fallback: if the selected provider is down the request fails.

```bash
# Offline and deterministic (the default). No key, no model.
LLM_PROVIDER=mock

# Google Gemini. Model ids retire, so set LLM_MODEL explicitly.
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash
GEMINI_API_KEY=...

# A local model through Ollama (you start Ollama and pull the model yourself).
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b
```

Apply a change with `docker compose up -d --build` (or restart `make dev`). Check the configured provider end to end with `python backend/scripts/llm_smoke.py`. `LLM_MODE` and `GEMINI_MODEL` are no longer accepted and stop startup with a message.

Representative supported questions in deterministic mock mode include:

- How many active vehicles do we have?
- What were the top 10 customers by revenue?
- Show monthly revenue for the last 12 months.
- Which vehicles had the highest idle time?
- Show fuel consumption by vehicle.

For follow-ups, send `conversation_id` on subsequent `/ask` calls. The backend retains at most eight recent turns and 2,000 context characters by default. Conversations are owner-scoped (another user gets a 404). They are durable in PostgreSQL with `CONVERSATION_STORE=postgres` (the Compose default) and in memory otherwise; results are never stored, only text. Caller context is untrusted prompt data, not an authorization input.

The repair loop is deliberately narrow: only classified repairable parse/schema/execution errors are sent back to the provider, with a configurable maximum of three attempts. Every repaired query returns through the same SQLGlot validator and read-only executor. Security, permission, timeout, complexity, and result-limit failures are not automatically repaired.

## Docker Compose

Copy `.env.example` to `.env`, replace both owner and read-only password placeholders with distinct credentials, and keep `.env` out of Git. Initialize and seed the database before starting the application:

```bash
docker compose up --build -d                  # starts PostgreSQL, runs migrations, then the backend and frontend
docker compose --profile demo run --rm seed   # demo data (refuses to run when APP_ENV=production)
```

Dashboard: http://localhost:3000. The backend is not published to the host; use `docker compose -f docker-compose.yml -f docker-compose.dev.yml up` to expose it on `127.0.0.1:8000` for debugging. Compose waits for PostgreSQL and backend readiness. The backend container is non-root with a read-only root filesystem, and both application images have health checks. Stop with `docker compose down`; do not add `--volumes` unless deleting database state is intended.

The PostgreSQL init script sets the `analytics_readonly` password only for new clusters. Changing environment variables does not rotate credentials in an already-initialized database; rotate both roles explicitly and update both connection URLs.

## Configuration and Operations

`APP_ENV=production` disables debug/docs and rejects SQLite URLs and mock LLM mode. Configure exact `CORS_ALLOWED_ORIGINS` only when direct cross-origin browser access is required; the Next proxy is same-origin by default. Pool sizes, connection/query/provider timeouts, request limits, rate limits, repair attempts, and result caps are environment-configurable. Do not put real secrets in image build args, source control, or logs.

Configuration lives in `.env.example` and the full setting-by-setting reference is in [docs/deployment.md](docs/deployment.md). Important values include `DATABASE_URL`, `ANALYTICS_DATABASE_URL`, distinct `POSTGRES_PASSWORD` and `ANALYTICS_DATABASE_PASSWORD`, `APP_ENV`, `LLM_PROVIDER`, `LLM_MODEL`, `GEMINI_API_KEY`, `CORS_ALLOWED_ORIGINS`, `MAX_REQUEST_BODY_BYTES`, `MAX_QUESTION_LENGTH`, `MAX_CONVERSATION_CONTEXT_CHARS`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`, pool settings, `QUERY_TIMEOUT_SECONDS`, `MAX_RESULT_ROWS`, and `MAX_REPAIR_RETRIES`.

`GET /health` is liveness; `GET /health/ready` is readiness and reports `degraded` (still HTTP 200) for optional dependencies such as the LLM key, so an orchestrator never restarts a healthy container over them. JSON logs carry request/conversation IDs and LLM, validation, SQL, repair, row-count, total-duration, and response-status metadata without logging questions, SQL, API keys, or full URLs. Every `/ask` and every rating also writes an audit event (principal, request id, SQL hash, tables, row count, duration, outcome; no question or SQL text).

**Durable and shared state.** `CONVERSATION_STORE=postgres` keeps conversations in PostgreSQL (retention `CONVERSATION_TTL_DAYS`, purge job `python -m app.jobs.purge`). The rate limit is kept in process memory, so run a single backend instance. `QUERY_COST_LIMIT` rejects queries whose PostgreSQL plan cost exceeds a budget before they run.

**Secrets as files.** Every secret setting accepts `NAME_FILE=/path`; startup validates the whole configuration and exits naming each bad setting (never its value). See [docs/operations.md](docs/operations.md).

**Observability.** `GET /api/v1/metrics/prometheus` (operator token) exposes histograms by route, LLM, validation, and SQL execution. Alert rules, SLO recording rules, a Grafana dashboard, and runbooks are in [`ops/`](ops/) and [`docs/runbooks/`](docs/runbooks/); objectives are in [docs/slos.md](docs/slos.md).

## Testing and CI

Backend:

```bash
make test          # unit tests (SQLite, mock provider)
make lint          # ruff
make typecheck     # mypy
make coverage      # tests with per-package coverage gates
make fuzz          # longer randomized validator run
make verify-permissions   # database privilege model (needs the Compose database)
pytest -m integration     # PostgreSQL: tenant isolation, durable conversations, query cost
make eval-check    # every golden-question reference query runs on the seeded database
make eval          # text-to-SQL evaluation (PROVIDER=mock|gemini|ollama, SUBSET=mock)
```

End to end and load:

```bash
make loadtest      # k6 against a backend started with docker-compose.loadtest.yml
```

Frontend:

```bash
cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
```

The backend smoke test exercises active vehicles, total revenue, top customers, monthly revenue, idle time, and fuel queries; it records SQL and total API latency.

GitHub Actions (`.github/workflows/`) runs on every push: backend lint, format check, mypy, unit tests with coverage gates and a seeded validator fuzz run, `pip-audit`; an integration job against PostgreSQL (init script, migrations with a downgrade round trip, seed, privilege verification, `pytest -m integration` with skips turned into failures, the evaluation dataset check and the deterministic evaluation subset); frontend lint, tests (including the API contract check), build, and `npm audit`; and Docker image builds with Trivy scans. Nightly it runs the full evaluation against the real model and a long fuzz run; weekly it runs the k6 load test. Releases are manual: tag, `docker compose up --build -d`, then run `scripts/smoke_test.py` (see [docs/operations.md](docs/operations.md)). Everything uses the mock provider unless a provider key is configured as a repository secret.

## Portfolio Notes

- **What I built:** an end-to-end conversational analytics MVP for fleet operations, from natural-language questions through validated SQL to a responsive results dashboard.
- **Why:** make operational and revenue questions accessible while keeping generated SQL explainable and constrained by an independent security boundary.
- **Engineering challenges:** maintaining a strict SQL trust boundary across generation, repair, and execution; bounding conversation and request size; and making provider/database failures observable without leaking sensitive input.
- **Technical decisions:** modular monolith rather than extra services; provider abstraction with deterministic mock mode; SQLGlot AST validation plus a separate PostgreSQL read-only role; backend-selected visualization metadata; and process-local metrics/rate limiting sized to the current Compose deployment.
- **Security considerations:** model output is untrusted; all generated and repaired SQL is revalidated; database URLs/keys are runtime secrets; request bodies and expensive endpoints are bounded; and errors/logging use request IDs without returning stack traces or recording questions/SQL.
- **Production-oriented work:** environment-specific settings, pooled connections and timeouts, health/readiness, structured telemetry, one bounded provider retry policy, non-root containers, distinct DB credentials, and automated CI checks. Authentication and tenant isolation are in the application; a managed production ingress, an identity provider, and shared multi-instance services are not.

## Limitations

The service validates signed tokens and scopes data per customer, but it has no identity provider: supply tokens carrying `sub`, `iss`, `aud`, `exp`, `roles`, and `customer_id`. There is no token revocation before expiry. Metrics are process-local counters (scrape every replica); there is no built-in log or metric aggregation. Result rows are never stored or cached, so a restored conversation shows its text but needs the question asked again to show data. Measured baselines: the deterministic mock evaluation is recorded in `docs/evaluation.md`. Evaluation baselines for Gemini and Ollama, the load-test saturation point, the restore drill and the rollback rehearsal have not been run; those documents describe how to take them.

Out of scope and not implemented: an identity provider integration, multi-replica scale-out, multi-region operation, embeddings, and automatic fallback between model providers (excluded on purpose). The project is closed; the final verification record is in [progress.md](progress.md).
