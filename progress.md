# AI SQL Analytics Copilot: Project Handoff

This document is the persistent context for future coding agents. Read it before changing the repository. The repository and its tests are the source of truth; this document is a handoff summary, not a replacement for inspecting the code.

## 1. Project Overview

**AI SQL Analytics Copilot** is a backend-first analytics product for fleet-management SaaS data. A user asks a natural-language business question, such as "What were the top customers by revenue?", and the system retrieves relevant schema context, generates read-only PostgreSQL SQL, validates it independently of the LLM, executes it against a restricted analytics database, and presents result intelligence in a conversational dashboard.

The target users are fleet operators, business analysts, and product/revenue teams who need answers from operational, utilization, maintenance, fuel, and billing data without hand-writing SQL. The project exists to make that workflow explainable and safer than allowing an LLM to execute arbitrary database output.

The technically interesting parts are the modular LLM provider boundary, deterministic schema/business-context retrieval, AST-backed SQL security, a separate PostgreSQL read-only role, bounded SQL repair, bounded conversation context, and post-query KPI/visualization analysis.

## 2. Current Status

```text
Current status: all planned work is complete. Sprints 1-15 are done, including the stabilization pass,
the simplification sequence (docs/Sequence.md), the LangChain model boundary (Sprint 13), Ollama,
optional LangSmith tracing and cross-provider evaluation (Sprint 14), and the closeout (Sprint 15).
The project is closed; section 25 is the closeout record: final verification, invariants, what was
and was not run, and the final Git state. Nothing further is planned.
```

| Sprint | Status | Description |
|---|---|---|
| Sprint 1 | COMPLETE | Repository foundation, FastAPI startup, configuration, logging, SQLAlchemy sessions, PostgreSQL Compose setup, tests, and developer tooling. |
| Sprint 2 | COMPLETE | Fleet-management PostgreSQL schema, Alembic migration, realistic deterministic seed data, indexes, schema metadata, and read-only analytics role. |
| Sprint 3 | COMPLETE | Analytics query/validation API, read-only execution service, result normalization, schema APIs, limits, timeouts, request IDs, and structured errors/logging. |
| Sprint 4 | COMPLETE | Natural-language SQL generation, schema retrieval, business definitions, provider abstraction, mock provider, `/generate`, `/ask`, response parsing, and bounded repair. |
| Sprint 5 | COMPLETE | SQLGlot AST validation, table/column allowlists, dangerous-function/system-table protection, complexity rules, normalized SQL, repair security, and security tests/docs. |
| Sprint 6 | COMPLETE | Result analyzer, KPI detection, deterministic visualization selection/validation, summaries, data-quality warnings, frontend-ready `/ask` responses, and visualization documentation. |
| Sprint 7 | COMPLETE | Bounded conversation context, follow-up-aware SQL generation, and conversation endpoints. |
| Sprint 8 | COMPLETE | Responsive Next.js dashboard, typed API integration, charts/results, Docker service, and frontend validation. |
| Sprint 9 | COMPLETE | Production configuration, API limits/rate controls, metrics, health/readiness, provider reliability, frontend failure handling, deployment docs, and CI. |
| Sprint 10 | COMPLETE | Final project documentation, portfolio narrative, verified handoff, and repository readiness. |
| Sprint 11 | COMPLETE (executed in the stabilization pass) | Security hardening and correctness: narrowed proxy, JWT auth, per-principal limits, PII-free tenant-scoped analytics views, function allowlist, LIMIT enforcement, SQLSTATE errors and repair hints, request deadline, prompt/retrieval fixes, result-intelligence fixes. |
| Sprint 12 | COMPLETE (executed in the stabilization pass; parts later removed) | Durable PostgreSQL conversations and audit trail, Prometheus metrics and alert rules, query-cost pre-flight, golden evaluation suite, fuzz tests, CI quality gates, runbooks. The Redis limiter, SQL cache, OpenTelemetry tracing, Kubernetes manifest and release pipeline built here were removed for the single-instance deployment (docs/Sequence.md section 18). |
| Stabilization | COMPLETE | First execution of Sprints 11-12; seven defects found and fixed (section 22). |
| Simplification | COMPLETE | Dead code, OpenAI provider, SQL cache, tracing, Redis limiter, Kubernetes/release pipeline, `static` auth and the e2e suite removed; every remaining recommendation decided (docs/Sequence.md sections 18-19). |
| Sprint 13 | COMPLETE | LangChain model boundary and explicit provider switching (section 23). |
| Sprint 14 | COMPLETE except live checks | Ollama, optional sanitized LangSmith tracing, cross-provider evaluation (section 24). Real Ollama inference, live Gemini evaluation and live LangSmith were not run. |
| Sprint 15 | COMPLETE | Closeout (section 25). |

Git history is summarized in section 21; older sprints were not tagged.

## 3. Product Capabilities

Implemented and verified capabilities:

- FastAPI modular monolith with health, schema, SQL, generation, conversation, feedback and combined analytics endpoints.
- PostgreSQL fleet-management dataset with deterministic demo seed data (100 customers, 1,000 vehicles, 50,000 trips and related tables).
- Schema-aware retrieval based on table/column/business terminology; the full schema is sent by default (11 tables).
- Business metric definitions for revenue, active vehicles, completed trips, fuel cost, idle time, and payments.
- **Explicit provider selection** through one factory: `mock` (deterministic, offline), `gemini` and `ollama` (both through LangChain chat models). No fallback between providers.
- Structured JSON model output parsed by one application-owned parser; malformed output is a classified failure, never guessed into SQL.
- One transient-retry policy and one bounded, deadline-aware repair loop; every repaired statement is validated again.
- Independent SQL safety: SQLGlot AST validation (SELECT-only, table and function allowlists, schema-qualifier and PII-column rules, joins/nesting/cartesian limits, outer `LIMIT` enforcement), comments stripped from the executed SQL, empty `SELECT`s rejected.
- Read-only execution: a separate `analytics_readonly` role with SELECT on tenant-scoped, PII-free `analytics` views only, a read-only transaction, `SET LOCAL` timeouts, an `EXPLAIN` cost pre-flight, and a row cap.
- Authentication (JWT in production, development bypass otherwise), per-principal rate limits (stricter for model calls), owner-scoped conversations, and a request-wide deadline.
- Conversation context with durable PostgreSQL storage (`CONVERSATION_STORE=postgres`) or in-memory, plus an audit trail that records identifiers and hashes, never content, and a feedback endpoint.
- Result intelligence after execution: KPI detection, deterministic table/kpi/bar/line/pie metadata with fallbacks, grounded deterministic summaries, formatting, warnings.
- Observability: structured JSON logs, Prometheus metrics (`/api/v1/metrics/prometheus`), a token-gated JSON snapshot, readiness with `degraded` semantics, an operator diagnostics route, alert rules, SLO rules, a Grafana dashboard and runbooks.
- Optional LangSmith tracing (off by default) that sends only allowlisted metadata with empty inputs and cannot block or fail a request.
- Evaluation: a 76-case golden dataset, a runner that reports coverage and failure classes honestly, seeded validator fuzz tests, and a smoke script for the configured provider.
- Next.js dashboard: same-origin proxy with an explicit route allowlist, CSP and security headers, sign-in, per-message results, restore on reload, delete, feedback, pagination, CSV export, distinct 401/429/504/422 states.
- Docker Compose (postgres, one-shot migrate, backend, frontend; demo and ops profiles), non-root read-only backend container, Dockerfiles, and GitHub Actions workflows (`ci.yml`, `nightly.yml`, `loadtest.yml`).

Known limitations are in section 16. Anything not listed above or there is not implemented.

## 4. Architecture

```text
User / API client
        |
        v
Next.js (UI + same-origin proxy with an explicit route allowlist)
        |
        v
FastAPI: request id, size limit -> authenticate (JWT) -> per-principal rate limit
        |
        v
SQLGenerationService  (request deadline starts)
   |        |
   |        +--> conversation context (owner-checked; memory or PostgreSQL)
   |
   +--> SchemaRetriever + business definitions
   |
   +--> LLMProvider  <-- built by app/llm/factory.py from LLM_PROVIDER
   |        mock (deterministic)  |  LangChainSQLProvider -> ChatGoogleGenerativeAI | ChatOllama
   |        UNTRUSTED output: parsed into {sql, explanation, tables_used, confidence}
   |
   v
AnalyticsQueryService   <- the safety boundary; knows nothing about LangChain
   |  SQLValidator (SQLGlot AST: allowlists, PII, LIMIT, comments stripped)
   |  read-only transaction + SET LOCAL timeouts + tenant scope + EXPLAIN cost check
   v
PostgreSQL as analytics_readonly  ->  tenant-scoped, PII-free `analytics` views  ->  tables
   |
   v   (repairable validation or execution error -> back to the provider, bounded, then validated again)
Result normalization -> KPI detection, VisualizationSelector, grounded summary
   |
   v
Frontend-ready response  ->  dashboard (conversation, KPI, chart, table, SQL)

Alongside: audit event per /ask, Prometheus metrics, JSON logs, optional sanitized LangSmith spans.
```

Responsibilities:

- **FastAPI/API layer:** validates request bodies, attaches request IDs, authenticates and rate limits, and maps internal errors to structured responses. It does not execute SQL directly.
- **Model factory (`app/llm/factory.py`):** the only place a provider is chosen or a client is constructed. LangChain supplies model invocation only; prompt policy, the response contract, error classification, retries and repair stay in the application.
- **SchemaRetriever:** deterministic keyword/column relevance; no embeddings or vector database.
- **SQLGenerationService:** coordinates question, context, provider output, bounded repair and execution. Generated SQL is never trusted.
- **SQLValidator and AnalyticsQueryService:** independent of the model layer (a test enforces that neither imports the other's packages).
- **Result intelligence services:** run only after successful execution and cannot influence SQL generation or execution.
- **Next.js frontend:** renders data and holds no SQL, validation or allowlist logic.
- **PostgreSQL:** the application/migration owner uses `DATABASE_URL`; generated SQL uses only the `analytics_readonly` role through `ANALYTICS_DATABASE_URL`.

## 5. Technology Stack

### Backend

- Python 3.12+ (developed and verified on 3.12.10)
- FastAPI and Uvicorn; Pydantic v2 and `pydantic-settings`
- SQLAlchemy 2.x, psycopg 3, Alembic
- SQLGlot for PostgreSQL AST parsing
- LangChain: `langchain-core`, `langchain-google-genai`, `langchain-ollama`
- `prometheus-client`, `pyjwt`
- pytest, pytest-cov, Ruff, mypy, pip-audit (development)

### Database

- PostgreSQL 16 via Docker Compose; three Alembic migrations (initial schema, `analytics` views, operational tables)
- Main tables: `customers`, `users`, `vehicles`, `drivers`, `trips`, `vehicle_locations`, `fuel_records`, `maintenance_records`, `invoices`, `payments`, and `subscriptions`; internal `seed_runs`; operational `conversations`, `conversation_turns`, `audit_log`

### AI

- `LLMProvider` protocol in `backend/app/llm/provider.py`
- Factory `backend/app/llm/factory.py`; `LangChainSQLProvider` in `backend/app/llm/langchain_provider.py`; error classification in `backend/app/llm/errors.py`
- `MockLLMProvider` in `backend/app/llm/mock_provider.py`; shared prompt (`prompt.py`) and parser (`parser.py`)
- Optional tracing in `backend/app/core/llm_tracing.py`
- Provider selection is `LLM_PROVIDER` (`mock`, `gemini`, `ollama`) and `LLM_MODEL`. Production rejects mock mode. Never copy secrets into documentation or commits.

### Frontend

- Next.js 16, React 19, TypeScript, Tailwind CSS, Recharts, Lucide React, Vitest, Testing Library, jsdom.
- `frontend/next.config.ts`: explicit proxy route list and security headers.
- `frontend/lib/api.ts`: typed API client; backend failures stay visible and are never replaced with fake results.
- Components: dashboard, question composer, results, charts, error panels, sidebar (see `frontend/components/`).

### Infrastructure

- Docker Compose services: `postgres`, one-shot `migrate`, `backend`, `frontend`; profiles `demo` (seed) and `ops` (purge). Health gates: PostgreSQL -> migrate -> backend -> frontend.
- Backend image: runtime dependencies only, non-root, read-only root filesystem in Compose. Frontend: standalone Next.js output, non-root.
- GitHub Actions: `ci.yml` (backend lint/types/tests/coverage/audit, PostgreSQL integration, frontend, image build and scan), `nightly.yml` (full evaluation against a real model if configured, long fuzz run), `loadtest.yml` (k6). The workflows' YAML parses; they have not run on a GitHub runner in this repository's recorded verification.
- `.env.example` documents configuration; `.env` is ignored and must never be committed.
- Make targets: `dev`, `test`, `lint`, `format`, `typecheck`, `coverage`, `fuzz`, `migrate`, `seed`, `verify-permissions`, `docker-up`, `docker-down`, `eval-check`, `eval`, `lock`, `lock-check`, `loadtest`, `purge`, `backup`, `restore-drill`.

## 6. LLM Architecture

The provider interface defines:

- `generate_sql(question, schema_context, conversation_context=None)`
- `repair_sql(question, original_sql, error_message, schema_context)`

`LangChainSQLProvider` (`app/llm/langchain_provider.py`), used for `gemini` and `ollama`:

- Wraps a LangChain chat model built by `app/llm/factory.py` (`ChatGoogleGenerativeAI` or `ChatOllama`); no other module constructs a provider client.
- Sends the rules as the system message and the data as the user message, in JSON mode, and parses the reply through the shared `parse_llm_response`; empty or malformed output is a controlled `INVALID_LLM_RESPONSE`.
- Classifies failures with `app/llm/errors.py` (walks the exception chain; never echoes provider text) and applies the only transient retry (`1 + LLM_MAX_RETRIES` attempts, infrastructure failures only). LangChain's own retries are off.
- Uses the same path for repair prompts. Does not validate or execute SQL.

`MockLLMProvider`:

- Is deterministic and supports representative active-vehicle, revenue, monthly-revenue, idle-time, and fuel questions.
- Is required for tests, CI, and credential-free local demos.
- Must be preserved when adding or changing providers.

Provider selection lives in `app/llm/factory.py` (called from `app/services/llm_dependencies.py`). Adding another provider should require a new factory branch, not changes to API routes, schema retrieval, SQL validation, or query execution.

The prompt builder includes PostgreSQL dialect rules, the user question, relevant schema, relationships, business definitions, read-only restrictions, and structured output instructions. Credentials and infrastructure URLs are never included.

## 7. SQL Generation Pipeline

```text
Natural-language question
        |
        v
SchemaRetriever
        |
        v
Relevant schema + business definitions
        |
        v
SQLPromptBuilder
        |
        v
LangChainSQLProvider (Gemini or Ollama) or MockLLMProvider
        |
        v
Structured LLM response parser
        |
        v
SQLGenerationService
        |
        v
SQLValidator / SQLGlot AST
        |
        v
AnalyticsQueryService
        |
        v
Read-only PostgreSQL
```

`/generate` stops after structured SQL generation. `/ask` continues into validation and execution. Repair is only attempted for classified repairable errors and each repaired query follows the same validator/executor path.

## 8. Security Architecture

The model is **not** a trusted security boundary, whichever provider is selected. The SQL validator, the database role and views, the read-only transaction and the execution limits are the actual defense layers, and none of them imports LangChain.

Current controls:

- **Authentication and tenancy.** Every analytics and schema route requires a principal. `AUTH_MODE=jwt` validates signature, expiry, issuer, audience and required claims with a configured algorithm only; `disabled` is development-only and production rejects it at startup and again at runtime. A non-admin token needs a `customer_id`. The tenant comes from the principal, never from the model path.
- **Tenant isolation and PII.** The analytics role reads only the `analytics` views: PII columns are absent, and rows are filtered by `app.scope` / `app.customer_id`, set per transaction with `SET LOCAL`; an unset scope returns no rows. The role has no privileges on the base tables.
- **Validator.** SQLGlot parses PostgreSQL SQL; one read-only `SELECT` or set operation (safe CTEs allowed); DML, DDL, transaction control, multiple statements, `SELECT INTO` and row locks are rejected; table and function allowlists; schema qualifiers other than `analytics` rejected; system catalogs and dangerous functions rejected; PII columns are security errors; every `SELECT` must select a column; joins, nesting and cartesian joins are limited; an outer `LIMIT` is enforced.
- **Executed SQL is the validator's own output.** `normalized_sql` is regenerated from the AST with comments stripped; the model's text is never executed.
- **Execution limits.** Read-only transaction, `SET LOCAL` statement/lock/idle timeouts, an `EXPLAIN` cost pre-flight (`QUERY_COST_LIMIT`), a row cap, and an overall request deadline.
- **Repair.** Bounded by `MAX_REPAIR_RETRIES` and the deadline; only classified repairable failures are repaired, security rejections never are, and every repaired statement is validated again.
- **Rate limiting.** Per principal, stricter for model calls; process-local.
- **Edge.** The frontend proxy forwards an explicit route list; direct SQL routes are unmounted in production unless enabled and are never forwarded; metrics and diagnostics need an operator token; the backend port is unpublished in Compose.
- **Providers and tracing.** Selection is explicit with no fallback; removed or unknown settings stop startup; provider errors are classified and never echo provider text; result rows are never sent to a model; optional LangSmith tracing sends only allowlisted metadata.
- **Secrets.** `*_FILE` variants, value-free startup errors, no secrets in logs, responses, the frontend bundle or traces (checked in the Sprint 15 closeout).

Known security limitations: nothing in this repository issues production tokens; AST validation is defense in depth rather than a complete guarantee (the views, role and read-only transaction are the hard boundary); a stolen JWT is valid until it expires; outside production, a `QUERY_GENERATION_FAILED` response carries a `debug` block with the failed SQL and a database error summary, which the dashboard shows and production never includes. Do not weaken the validator, the views or the role to make a generated query work.

## 9. Database

PostgreSQL is created by `docker-compose.yml`. Alembic owns schema creation; do not replace migrations with `Base.metadata.create_all()` in application startup. In Compose the one-shot `migrate` service runs `alembic upgrade head` and the backend waits for it.

Migrations: `9a999e64b310` (initial analytics schema), `b7c2d41f8a10` (the `analytics` schema of tenant-scoped, PII-free views and `analytics.row_visible()`), `c3d91e5a7b20` (operational tables: `conversations`, `conversation_turns`, `audit_log`, on their own base so they can never enter the analytics allowlist). Upgrade, downgrade to the first revision, and re-upgrade were run in the closeout.

The deterministic seed in `backend/app/db/seed.py` (seed `20260923`, 2024-2025, protected by `seed_runs`, refuses to run in production, and runs `ANALYZE` so the cost pre-flight sees real row counts) creates: 100 customers, 354 users, 1,000 vehicles, 500 drivers, 50,000 trips, 20,000 vehicle locations, 20,000 fuel records, 10,000 maintenance records, 10,000 invoices, 20,000 payments, 100 subscriptions.

The `app` role owns and migrates the schema. `analytics_readonly` can connect and SELECT from the `analytics` views only. `database/verify-readonly.sql` checks this (`make verify-permissions` runs it inside Compose; it reports "analytics_readonly permissions verified"). The analytics service always uses `ANALYTICS_DATABASE_URL`, never the owner URL.

## 10. Result Intelligence

Sprint 6 runs after successful SQL execution:

- `AnalyticsResultAnalyzer` profiles columns as numeric, categorical, datetime, identifier, or unknown using returned values and database-derived types.
- It detects aggregate-like names, currency/percentage/integer/decimal formatting, NULL fractions, and KPI eligibility.
- A KPI requires one row, a numeric non-identifier measure, and KPI-like question language. Examples include total revenue, active vehicle count, and average trip distance.
- `VisualizationSelector` chooses `kpi`, `line`, `bar`, `pie`, or `table` deterministically.
- Datetime + numeric selects line; category + numeric selects bar; small distributions up to six categories select pie; complex or invalid data falls back to table.
- Axis fields are validated against returned columns and empty data always falls back to table.
- Values remain machine-readable: Decimal becomes a JSON number, temporal values become ISO strings, UUIDs become strings, and NULL stays NULL.
- Empty results return a no-records summary and warning rather than an error. High NULL fractions produce warnings.
- `ResultSummaryService` produces deterministic grounded summaries from returned data only. `ENABLE_RESULT_SUMMARY=false` disables them. No model is called to write summaries.

## 11. API Surface

All routes are under `/api/v1` unless noted. Analytics and schema routes require a bearer token unless `AUTH_MODE=disabled` (development only).

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Dependency-free liveness probe (also under `/api/v1`). |
| GET | `/health/ready` | Readiness: 503 if a required database is down; 200 `{"status": "degraded", "degraded": ["llm_provider"]}` if only the provider is unconfigured. Never calls the provider. (Also `/api/v1/health/ready`.) |
| GET | `/api/v1/health/diagnostics` | Operator-only: dependency latency, pools, migration revision, enabled features, provider and model. Needs `METRICS_TOKEN`. |
| GET | `/api/v1/metrics` | JSON counter snapshot. Needs `METRICS_TOKEN` when set; 404 in production when unset. |
| GET | `/api/v1/metrics/prometheus` | Prometheus exposition (same protection). |
| POST | `/api/v1/analytics/ask` | Generate SQL, validate, execute, and return rows plus summary, KPI, visualization, warnings and `request_id`. |
| POST | `/api/v1/analytics/generate` | Question to structured SQL without execution. |
| POST | `/api/v1/analytics/query` | Direct read-only SQL. **Mounted only outside production or with `ENABLE_DIRECT_SQL_ENDPOINTS`; never forwarded by the frontend proxy.** |
| POST | `/api/v1/analytics/validate` | Validate without executing. Same mounting rule as `query`. |
| POST / GET / DELETE | `/api/v1/analytics/conversations`, `/{id}`, `POST /{id}/turns` | Create, read, delete and append to an owner-scoped conversation. |
| POST | `/api/v1/analytics/feedback` | Record a helpful / not-helpful rating for a request id. |
| GET | `/api/v1/schema`, `/schema/tables`, `/schema/tables/{table_name}`, `/schema/business-definitions` | Schema metadata (PII-free), business definitions and example questions. |
| GET | `/docs`, `/openapi.json` | Interactive docs; disabled in production. |

Errors use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`. Codes include validation, parse, security, permission, timeout, cost, table-not-found, generation-failed, the model codes in `docs/llm-providers.md`, invalid-request, request-too-large, deadline, unauthenticated/forbidden, and rate-limit errors.

## 12. Repository Structure

```text
ai-sql-analytics-copilot/
├── backend/
│   ├── app/
│   │   ├── analytics/       # AST validator, read-only executor, normalization
│   │   ├── api/             # FastAPI routes: analytics, generation, conversations, feedback, schema, health
│   │   ├── conversation/    # context store: in-memory and PostgreSQL
│   │   ├── core/            # settings, auth, rate limit, metrics, audit, deadline, telemetry, logging, llm_tracing
│   │   ├── db/              # engines, models base, seed, schema metadata, analytics views, operational tables
│   │   ├── jobs/            # retention purge
│   │   ├── llm/             # factory, LangChain provider, errors, mock provider, prompt, parser, protocol
│   │   ├── models/          # SQLAlchemy entities
│   │   ├── schemas/         # Pydantic API contracts
│   │   ├── services/        # retrieval, generation, result intelligence
│   │   └── main.py
│   ├── alembic/versions/    # three migrations
│   ├── evals/               # golden dataset, runner, scoring, thresholds
│   ├── scripts/             # check_coverage.py, issue_token.py, llm_smoke.py
│   ├── tests/               # 29 test modules (unit, security, provider, wire-level, tracing, integration)
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                # Next.js dashboard, proxy config, contract, tests
├── database/                # init/01-analytics-role.sql, verify-readonly.sql
├── docs/                    # see docs/README.md for the index
├── ops/                     # Prometheus alerts and SLO rules, Grafana dashboard
├── scripts/                 # smoke_test.py, backup/restore scripts
├── loadtest/                # k6 script
├── .github/workflows/       # ci.yml, nightly.yml, loadtest.yml (+ dependabot.yml)
├── docker-compose.yml       # + docker-compose.dev.yml, docker-compose.loadtest.yml
├── .env.example  Makefile  README.md  progress.md
└── sprints.md  final_sprints.md   # historical plans; see section 25
```

## 13. Environment Variables

`docs/deployment.md` is the complete, setting-by-setting reference (a closeout check confirmed every setting in `Settings` appears in the documentation). The ones that matter most:

| Variable | Notes |
|---|---|
| `APP_ENV` | `development` (default), `test`, `production`. Production requires PostgreSQL, JWT auth and a real provider, and disables docs, debug blocks and the mock. |
| `DATABASE_URL`, `ANALYTICS_DATABASE_URL` | Owner and read-only connections; never the same role. |
| `POSTGRES_PASSWORD`, `ANALYTICS_DATABASE_PASSWORD` | Required by Compose; distinct. |
| `LLM_PROVIDER`, `LLM_MODEL` | `mock` (default), `gemini`, `ollama`; model id (Ollama requires it). `LLM_MODE` and `GEMINI_MODEL` no longer exist and stop startup. |
| `GEMINI_API_KEY`, `OLLAMA_BASE_URL` | Key for Gemini (secret; `_FILE` works); Ollama address (default `http://127.0.0.1:11434`, `host.docker.internal` in Compose). |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `MAX_REPAIR_RETRIES`, `REQUEST_DEADLINE_SECONDS` | The single timeout, retry and deadline policy. |
| `AUTH_MODE`, `JWT_*` | `jwt` or `disabled`; issuer, audience and key settings. |
| `ENABLE_DIRECT_SQL_ENDPOINTS`, `METRICS_TOKEN` | Exposed-surface switches. |
| `CONVERSATION_STORE`, `AUDIT_SINK`, `*_TTL/RETENTION_DAYS` | `memory` or `postgres`; `log`, `database` or `both`. |
| `RATE_LIMIT_*`, `QUERY_TIMEOUT_SECONDS`, `QUERY_COST_LIMIT`, `MAX_RESULT_ROWS`, `MAX_QUERY_*` | Limits. |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` | Optional tracing, off by default. |
| `RUN_LIVE_LLM_TESTS` | Test-time switch for the opt-in live provider tests. |

Values belong in an ignored `.env` or a secret store, never in this file or Git.

## 14. Testing

Backend tests are in `backend/tests` (pytest, 29 modules); frontend tests in `frontend/` (Vitest). Areas covered:

- API, configuration, database constraints, deterministic seed, health and readiness, error sanitization.
- Authentication, per-principal limits, owner-scoped conversations, proxy route allowlist and headers.
- SQL safety: allowed and forbidden queries, function and table allowlists, PII columns, LIMIT enforcement, comments stripped, empty `SELECT`s rejected, repair security, and a seeded fuzz suite (default size in CI, 20,000 iterations nightly).
- Provider boundary: factory selection and configuration failures, structured parsing, error classification, one retry policy, wire-level tests of the real Gemini and Ollama clients against local servers (including counting HTTP requests), and no-network proof.
- Tracing: sanitization, end-to-end non-leakage, the real LangSmith client against a local server, outage and circuit-breaker behaviour, process-exit time.
- Security invariants across providers: the model layer cannot reach the database, the SQL layer does not depend on LangChain, forbidden SQL never opens a connection for any provider, secrets and provider text do not reach responses or logs.
- PostgreSQL integration (marked `integration`): read-only privileges, tenant isolation through joins, CTEs, subqueries and unions, durable conversations, cost pre-flight, migrations. With `REQUIRE_INTEGRATION=1` a missing database fails instead of skipping.
- Evaluation: scoring, comparison, summary and report logic, and the dataset itself.
- Opt-in live provider tests (`live`, skipped unless `RUN_LIVE_LLM_TESTS=1`).

Commands (from the repository root unless noted):

```bash
make lint typecheck test coverage fuzz        # backend; `make coverage` also runs the per-package gates
cd backend && python -m pytest -m integration # needs migrated, seeded PostgreSQL (see ci.yml for the setup)
cd frontend && npm ci && npm run lint && npm test -- --run && npm run build
```

Closeout results are in section 25. Earlier counts quoted in sprint summaries are historical.

## 15. Completed Sprint Summary

Historical record, written as each sprint finished. Later work superseded parts of it: Sprint 9's process-local conversations and Gemini SDK calls, Sprint 11's default model, and several Sprint 12 components (see section 2 and `docs/Sequence.md`). The current state is in the other sections.

### Sprint 1 — Foundation

- **Objective:** establish the modular monolith and developer infrastructure.
- **Implementation:** FastAPI app, `/health`, settings, logging, SQLAlchemy sessions, Docker Compose, Makefile, pytest, Ruff, README, and architecture docs.
- **Significance:** created the application/database boundary that later services depend on.

### Sprint 2 — Database Schema and Dataset

- **Objective:** create realistic fleet-management SaaS analytics data.
- **Implementation:** eleven business tables, relationships, constraints, indexes, Alembic migration, deterministic seed, schema metadata, and the `analytics_readonly` role.
- **Significance:** supplied real data and enforced privilege separation before any LLM was trusted with query generation.

### Sprint 3 — Analytics API Foundation

- **Objective:** execute direct SQL through a controlled service.
- **Implementation:** `/analytics/query`, `/analytics/validate`, schema APIs, analytics engine, result normalization, row/time limits, structured errors, request IDs, and logs.
- **Significance:** separated HTTP, validation, read-only execution, and result serialization.

### Sprint 4 — Natural Language to SQL

- **Objective:** convert questions into structured SQL without executing raw LLM output.
- **Implementation:** provider protocol, mock provider, Gemini provider, prompt builder, parser, schema retrieval, business definitions, `/generate`, and `/ask`.
- **Significance:** made provider choice replaceable and kept generation separate from execution.

### Sprint 5 — SQL Security and Repair

- **Objective:** make generated SQL untrusted and enforce production-grade validation.
- **Implementation:** SQLGlot AST validation, allowlists, dangerous-function/system-table controls, column checks, complexity rules, normalized SQL, read-only enforcement, bounded repair, security docs, and security tests.
- **Significance:** placed the actual security boundary outside the LLM and revalidated every repair.

### Sprint 6 — Result Intelligence and Visualization

- **Objective:** transform raw execution output into frontend-ready analytics metadata.
- **Implementation:** result analyzer, typed KPI/visualization contracts, deterministic selector, table fallback, formatting, warnings, grounded summaries, `/ask` response extension, docs, and tests.
- **Significance:** kept visualization and summary decisions backend-owned and independent of a future frontend.

### Sprint 7 — Conversational Analytics and Context Management

- **Objective:** support multi-turn questions without unbounded prompt history.
- **Implementation:** bounded in-memory conversation turns, context injection into generation, and conversation session endpoints.
- **Significance:** lets follow-up questions reuse context while keeping the SQL security pipeline unchanged.

### Sprint 8 — Analytics Dashboard / Frontend

- **Objective:** provide a usable conversational interface for backend analytics responses.
- **Implementation:** modular Next.js dashboard, typed API client, same-origin API proxy, KPI/chart/table/SQL result views, local conversation switching, responsive layout, frontend tests, standalone Docker image, and Compose integration.
- **Verification:** frontend tests and lint pass; Next.js production build and frontend Docker image build pass; full Compose stack started and `/api/v1/analytics/ask` smoke-tested through the frontend proxy. (At the time the demo used a mock-mode override; the setting has since been renamed `LLM_PROVIDER`.)
- **Significance:** completes the user-facing analytics workflow without moving business or SQL security rules into the browser.

### Sprint 9 — Production Hardening, Observability, and Deployment

- **Objective:** harden the current modular monolith as a production-oriented MVP without adding infrastructure.
- **Implementation:** production/development settings, secret masking, configurable CORS and request/rate limits, structured request-correlated errors, security headers, SQLAlchemy pool controls, health/readiness, process-local metrics, detailed request/provider/validation/SQL/repair telemetry, bounded Gemini transient retries, classified provider/database errors, improved frontend retries/error boundaries, non-root/minimal containers, distinct DB role credentials, GitHub Actions CI, deployment and security review documents, and representative SQL/API latency smoke coverage.
- **Validation:** 99 backend tests passed with one PostgreSQL-only permission test skipped; 11 frontend tests passed; Ruff, ESLint, Next production build, Compose config, both container builds, container health checks, and full-stack health/API/metrics smoke tests passed. Production frontend audit reported zero vulnerabilities. A fresh PostgreSQL 16 init verified distinct owner/read-only password authentication.
- **Significance:** improves reliability and operational clarity while preserving the existing SQL security boundary; multi-instance and tenant controls remain explicit future work.

### Sprint 10 — Final Documentation and Portfolio Polish

- **Objective:** make the completed project understandable, verifiable, and ready for repository/portfolio review without adding functionality.
- **Implementation:** refreshed the README overview, end-to-end architecture, API inventory, representative questions, conversation behavior, SQL validation/repair model, configuration, test/Docker instructions, limitations, and portfolio narrative; reconciled architecture, security, conversation, database, and handoff docs; removed stale sprint/Git references.
- **Validation:** verified documentation claims against the implemented routes/configuration, reviewed recent Git history and the clean starting worktree, checked stale sprint references, and ran `git diff --check`. No application code, tests, CI, Docker, schema, or infrastructure files were changed in Sprint 10.
- **Significance:** provides a technically credible account of both the production-oriented controls and the remaining non-enterprise limitations.

### Sprint 11 — Security Hardening and Correctness

Implemented from `sprints.md` (S11-01 to S11-22). It was first executed in the stabilization pass (section 22).

- **Surface:** `frontend/next.config.ts` proxies an explicit route list only; `/query` and `/validate` are unmounted in production unless `ENABLE_DIRECT_SQL_ENDPOINTS`; `/metrics` needs `METRICS_TOKEN`; Compose publishes no backend port (`docker-compose.dev.yml` does, locally); Next.js sends CSP/frame/HSTS headers.
- **Auth and limits:** `app/core/auth.py` (JWT / static / disabled; production requires JWT), `app/core/rate_limit.py` (per-principal route dependency, stricter LLM limit), owner-scoped conversations with user-only turns, TTL and caps.
- **Data protection:** migration `b7c2d41f8a10` creates the `analytics` schema of PII-free, tenant-filtered views (`analytics.row_visible()` reading `app.scope` / `app.customer_id`); the role has no `public` privileges; the executor runs `SET TRANSACTION READ ONLY` plus `SET LOCAL` timeouts and tenant settings and uses `exec_driver_sql`. Deviation from the sprint text: tenant scoping lives in the views, not in RLS policies, because the view owner bypasses RLS.
- **Validator:** function allowlist, schema-qualifier and PII-column rules, derived-table aliases, allowlist derived from metadata, outer `LIMIT` enforcement with truncation.
- **Errors and repair:** SQLSTATE classification, `repair_hint` separate from the public message, conversation context in repair, `QUERY_GENERATION_FAILED` (422), and an overall request deadline (`REQUEST_DEADLINE_SECONDS`).
- **Prompting:** full schema in every prompt, follow-up-aware retrieval, current date, enum values, system instruction, temperature 0, one shared repair prompt, assistant turns store SQL/tables, Gemini attempts reduced to 2, default model pinned to `gemini-2.5-flash` (verify it is available to your account).
- **Results:** structural KPI detection, column-name-only formatting, multi-series charts, additive-only pies, distinct colours, short titles, direction-aware summaries; frontend sign-in prompt, generation-failed panel, truncated marker.

## 16. Known Limitations

- **No identity provider.** The API validates signed tokens and scopes queries to the token's customer, but nothing in this repository issues production tokens (`backend/scripts/issue_token.py` is a development helper). A stolen token is valid until it expires; there is no revocation list.
- **Single instance.** Rate limiting and the JSON metrics are process-local, so several replicas would each enforce their own limit. Conversations are durable with `CONVERSATION_STORE=postgres`.
- **Development error detail.** Outside production a `QUERY_GENERATION_FAILED` response includes a `debug` block (failed SQL and a database error summary), by design for the dashboard. Do not run a non-production environment with untrusted users.
- **Readiness does not call the model provider.** An unreachable Ollama or a Gemini outage shows in request errors and metrics, not in readiness; `backend/scripts/llm_smoke.py` checks a provider end to end.
- **Model behaviour is external.** Gemini model ids retire (the previous default now returns 404 for new users), capacity and quota errors occur, and Gemini 3 models ignore `temperature`, so real-model results vary between runs. Only the mock is deterministic.
- **Live checks not run in this environment.** Inference with a real Ollama model, a live Gemini evaluation on the final code, and live LangSmith were not run (section 25). No Gemini or Ollama evaluation baseline or threshold exists yet.
- **AST validation is defense in depth.** The tenant views, the read-only role and transaction, and the limits are the hard boundary.
- **Tracing shares metadata.** When enabled, request ids and timings go to LangSmith (see `docs/security.md`).
- **PostgreSQL init passwords apply only to fresh clusters.** Existing roles need explicit rotation and URL updates.
- **Compose is a single-host setup.** Production needs private networking, a TLS gateway, and a secret manager.
- **No backend lockfile.** `requirements.lock` does not exist (`make lock` was not run); dependency ranges are in `pyproject.toml` and `pip-audit` was clean at closeout.
- **CI has not run on GitHub in the recorded verification.** The workflow files parse and every command they run was exercised locally on Windows; the first run on a Linux runner is the remaining confirmation. The k6 load test and Trivy image scans were not run.
- **Schema retrieval is keyword-ordered.** The full schema is sent by default (11 tables); no embeddings or vector store exist.
- **Deterministic summaries.** No model writes summaries.

## 17. Out of Scope

Deliberately not part of this project, and not planned:

- An identity provider integration or token issuing.
- Multi-replica scale-out (a shared rate limiter and metrics aggregation).
- Embeddings or a vector database for schema retrieval.
- Automatic fallback between model providers (excluded on purpose: it could send data somewhere the operator did not choose).
- Cloud deployment automation or a managed observability platform.
- Agentic tool loops (LangGraph) or fine-tuning.

Each of these would be a new requirement, not unfinished work.

## 18. How to Resume Development

```text
The project is closed. Sprints 1-15 are complete; section 25 is the closeout record.

If work is requested:
1. Read this file, README.md, docs/README.md and docs/llm-providers.md.
2. Check `git status` and `git log`; the repository and its tests are the source of truth.
3. Run the checks listed in section 14 before changing anything, and record what you ran.
4. Preserve the SQL safety boundary and the explicit-provider, no-fallback rule.
5. Update this file with evidence; never mark work complete without it.
```

## 19. Instructions for Future AI Agents

- Read `progress.md` before modifying the project, and treat the repository and tests as the source of truth.
- Inspect existing code before implementing anything. Do not rewrite working architecture or duplicate functionality.
- Never bypass SQLGlot validation, the tenant views, or the read-only analytics service. Never let model output execute outside that pipeline.
- Never trust model confidence, explanations, summaries, or visualization metadata as security controls. Keep LangChain and LangSmith out of every security decision.
- Never add automatic fallback between providers.
- Never commit `.env`, keys, passwords, tokens, or database credentials, and do not print secrets while debugging.
- Keep the `LLMProvider` protocol and the deterministic mock. Keep all live calls (Gemini, Ollama, LangSmith) optional in tests.
- Preserve the separate `DATABASE_URL` and `ANALYTICS_DATABASE_URL` roles, and keep migrations as the schema authority.
- Keep result intelligence independent of frontend code.
- Add focused tests for new behaviour and keep regression coverage; report checks that were not run as not run.
- Do not mark work complete unless its acceptance criteria were verified, and update this file after finishing.
- Do not commit changes unless explicitly instructed.

## 20. Important Development Decisions

- **One model boundary, no fallback.** The API depends on the `LLMProvider` protocol and a single factory; LangChain is used only to call the model. A failing provider is an error, never a silent switch.
- **Mock mode.** Deterministic offline SQL keeps development, CI and demos independent of any service.
- **Independent SQL validation.** The model is untrusted; SQLGlot, allowlists, the tenant views, the read-only role and limits enforce safety outside it, and the two layers do not import each other.
- **Separate database roles.** Migrations and application code use the owner URL; generated SQL uses `analytics_readonly` against views.
- **Repair revalidation.** A repaired query takes exactly the same validator and executor path; security errors are never repaired.
- **Single instance.** Simplicity over scale-out; the removed components are recorded in `docs/Sequence.md`.
- **Tracing is optional and sanitized.** Empty inputs, an allowlist, a bounded queue, and no effect on a request.
- **Honest evaluation.** Coverage is reported separately from accuracy; provider failures and declines are never counted as passes or as safety rejections.
- **Deterministic retrieval and visualization.** Predictable and testable; embeddings and model-chosen charts were not needed.
- **Migration-owned database.** Alembic creates the schema; the seed is idempotent and refuses to run in production.

## 21. Current Git State

- **Branch:** `main`.
- **Sprint 15 baseline:** `b1e07c2` (Sprint 14, committed by the owner) with a clean tree.
- **Earlier milestones:** Sprint 13 `19213a2`; e2e removal `622a59e`; validator fixes `3bd332a`; simplification `412752b` and `d4ff27a`; stabilization `08317e3`; Sprint 12 `23e1de5` (`e869768` is an identical-tree duplicate); Sprint 11 `abd5ac3`; Sprint 9 `e1291e4`.
- **Sprint 15 changes are uncommitted** in the working tree, by instruction. The final checkpoint is recorded in section 25.

No secrets, API keys, passwords, or token values belong in this file.

## Sprint 12: reliability, quality gates, operations (historical; parts since removed)

> Historical record. The Redis limiter, SQL cache, OpenTelemetry tracing, Kubernetes manifest and release pipeline described below were later removed (section 2 and `docs/Sequence.md` section 18). Everything else still stands.

Written without running anything; the stabilization pass in section 22 later executed the backend, frontend, PostgreSQL/Redis integration and Docker Compose paths. Items that still need a real environment are listed there under "Not run".

- State: `ConversationStore` interface with in-memory and PostgreSQL implementations (`app/conversation/sql_store.py`, migration `c3d91e5a7b20`, operational tables on their own base); optional SQL cache; `python -m app.jobs.purge`.
- Safety: `EXPLAIN` cost pre-flight (`QUERY_COST_LIMIT`), `*_FILE` secrets with value-free startup errors, demo seed refuses production, validator now catches tokenizer/recursion errors.
- Observability: Prometheus metrics (`/api/v1/metrics/prometheus`), audit trail, readiness `degraded` semantics, operator diagnostics.
- Quality: PostgreSQL integration CI, golden evaluation suite (76 cases, `backend/evals`), validator fuzzing, coverage gates, mypy, supply-chain scans, API contract test.
- Ops: alerts, SLO rules, Grafana dashboard, five runbooks, k6 load test, smoke test, backup/restore/drill scripts, `docs/operations.md`, `evaluation.md`, `slos.md`, `capacity.md`, `threat-model.md`.
- Frontend: result kept per message, restore on reload, delete, feedback, examples panel, pagination, CSV export, 401/429/504/422 states, schema-validated responses.
- Pending real-environment evidence: first evaluation baseline against Gemini, load-test saturation numbers, restore drill, rollback rehearsal, `make lock` (no `requirements.lock` yet). `ruff format` and the mypy cleanup were completed in section 22.


## 22. Stabilization pass (verified checkpoint)

Scope: make the existing project run, test, build and start; no rewrite, no feature work, and none of the simplification candidates in `docs/Sequence.md` were touched.

**Starting point:** `main` at `6ea3d59`, clean tree. Sprints 11 and 12 had been written without ever being executed. Environment used: Windows 10, Python 3.12.10, Node 24, Docker 29 with Compose 5. The installed FastAPI (0.143), Starlette (1.7) and sqlglot (27.29) are the newest releases the `pyproject.toml` ranges allow; there is no lockfile yet, so Docker builds resolve to the same newest versions.

### What was broken and what fixed it

| # | Defect | Root cause | Fix | Regression test |
|---|---|---|---|---|
| 1 | Any query with `AND` / `OR` was rejected: "Function And is not available" | In sqlglot 27.29, `exp.And`/`exp.Or` are subclasses of `exp.Func`, so the function allowlist in `SQLValidator._function_violations` treated boolean connectors as unknown functions. This made most generated SQL invalid, triggered the repair loop, and caused `REQUEST_DEADLINE_EXCEEDED` with Gemini. | Skip `exp.Connector` nodes in `_function_violations` (`backend/app/analytics/validator.py`). Restricted functions are still detected inside compound conditions. | `test_boolean_connectors_are_not_treated_as_functions`, `test_connectors_do_not_hide_a_restricted_function` in `tests/test_sql_security.py` |
| 2 | Metric `route` labels and the log `endpoint` field lost the `/api/v1` prefix (e.g. `/analytics/ask`) | FastAPI 0.143 keeps included routers nested; `scope["route"].path` is relative to the include prefix. | `_route_template()` in `backend/app/main.py` restores the full template from the request path. Works with old and new FastAPI. | existing `test_http_metrics_use_the_route_template_not_the_raw_path` (was failing) |
| 3 | `EXPLAIN` cost pre-flight did not reject an expensive self-join on a freshly seeded database | The seed never ran `ANALYZE`; without statistics the planner assumed ~2,900 rows for `trips` (50,000), so the estimated cost stayed below `QUERY_COST_LIMIT` until autovacuum ran. | `backend/app/db/seed.py` now runs `ANALYZE <table>` for each seeded table (PostgreSQL only). | existing integration test `test_expensive_query_is_rejected_before_it_runs` (was failing) |
| 4 | `test_direct_sql_routes_are_mounted...` failed | The test read `app.routes`, which no longer lists included routers flat. Application behaviour was correct. | Test now reads paths from `app.openapi()`. | itself |
| 5 | Fuzz test "known-good statements stay valid" failed | sqlglot cannot parse a comment between the words of `GROUP BY` / `ORDER BY` / `PARTITION BY`. The validator rejects such input (fail closed, safe); the mutator in the test inserted exactly that. | The test mutator keeps those keyword pairs together. Validator unchanged. | itself |
| 6 | Two parametrized hostile-input tests errored on Windows | pytest put the 50 KB SQL string into `PYTEST_CURRENT_TEST`, above the 32,767-character environment-variable limit. | Explicit `ids=` on the parametrization. | itself |
| 7 | CI would fail `ruff check`, `ruff format --check`, `mypy` | 2 unsorted import blocks, 14 unformatted files, 34 mypy errors in 10 files. | `ruff --fix` / `ruff format` (mechanical) and typing-only fixes (Optional narrowing in the validator, `Literal` kinds/roles, `Any` for untyped driver objects, `cast` for validated roles). No behaviour change. | mypy and ruff pass |

Files changed (all under `backend/` unless noted): `app/analytics/validator.py`, `app/analytics/service.py`, `app/main.py`, `app/db/seed.py`, `app/db/session.py`, `app/db/schema_metadata.py`, `app/core/config.py`, `app/core/logging.py`, `app/core/audit.py`, `app/conversation/service.py`, `app/conversation/sql_store.py`, `app/services/result_analyzer.py`, plus formatting-only changes in `app/api/analytics.py`, `app/api/schema.py`, `app/llm/gemini_provider.py`, `app/services/visualization.py`, `alembic/versions/c3d91e5a7b20_*.py`, `evals/scoring.py`; tests: `test_sql_security.py`, `test_production_hardening.py`, `test_validator_fuzz.py`, `test_generation.py`, `test_analytics_smoke.py`, `test_database.py`; docs: `progress.md`, `README.md`, `docs/Sequence.md`.

### Commands run and actual results

| Area | Command | Result |
|---|---|---|
| Backend lint | `python -m ruff check .` | Passed |
| Backend format | `python -m ruff format --check .` | Passed (106 files) |
| Backend types | `python -m mypy` | Passed (68 source files) |
| Backend unit tests | `python -m pytest -m "not integration"` | Passed: 404 passed (before the fixes: 6 failed, 2 errors) |
| Coverage gates | `pytest ... --cov=app` then `scripts/check_coverage.py` | Passed: analytics 94.0%, services 94.7%, llm 86.9% (overall 92%) |
| Integration | fresh PostgreSQL 16 + Redis 7 containers, `REQUIRE_INTEGRATION=1`, `python -m pytest -m integration` | Passed: 45 passed, 0 skipped (before the fixes: 1 failed) |
| Migrations | `alembic upgrade head` on an empty database; `downgrade 9a999e64b310` then `upgrade head` | Passed (3 revisions up; 2 down, 2 up) |
| Privilege model | `database/verify-readonly.sql` | Passed ("analytics_readonly permissions verified") |
| Evaluation | `python -m evals.run_eval --check-references`; `--provider mock --subset mock` | Passed: 76 cases, 0 reference problems; mock subset: 9 cases, 5 scored, 5 passed (execution accuracy 1.0) |
| Frontend lint | `npm run lint` | Passed |
| Frontend tests | `npm test -- --run` | Passed: 11 files, 122 tests |
| Frontend types | `npx tsc --noEmit` | Passed after `npm run build` (the `LayoutProps` type is generated by Next during the build, so bare `tsc` on a fresh checkout reports it missing) |
| Frontend build | `npm run build` | Passed |
| Compose config | `docker compose config -q` (base, `+dev`, `+loadtest`) | Passed |
| Images | `docker compose up --build` in a separate project (`copilot-verify`) | Passed: backend, frontend, migrate, seed images built; all services healthy |
| Mock end to end | `POST /api/v1/analytics/ask` through the frontend proxy | Passed: KPI (766 active vehicles), bar (top 10 customers), line (13 monthly revenue rows); summaries present |
| Proxy allowlist | `POST /api/v1/analytics/query`, `/validate`, `GET /metrics` through the proxy | Passed: HTTP 404 |
| Durable conversations | create, two asks, read back, `restart backend`, read back | Passed: 4 turns before and after restart; 4 `audit_log` rows written |
| Gemini (live) | two questions with `LLM_MODE=gemini`, `gemini-flash-latest`, throwaway backend | Passed: both answered (4.5 s and 8.6 s), both questions use `AND` |

The verification stack used its own PostgreSQL and was removed afterwards. The running `ai-sql-analytics-copilot` stack and its database volume were not modified; it is still running the images built before these fixes (see below).

### Not run / blocked

- The k6 load test (the Playwright end-to-end suite was removed at the owner's request), Trivy image scans, `pip-audit`, `npm audit`, and the long fuzz run: not run in this pass.
- Lockfile (`make lock` / `lock-check`): no `backend/requirements.lock` exists; the CI step only warns.
- JWT authentication and tenant isolation were verified by unit and integration tests only, not by a live JWT request against the Compose stack (the Compose run used `AUTH_MODE=disabled`, which production rejects). **Closed afterwards:** a live JWT run on an isolated Compose stack passed 19 of 19 tenant-isolation checks (see `docs/Sequence.md` section 19).
- Gemini was verified with two live calls only; it is not part of the deterministic suite. External failures (quota, latency, model changes) are not reproducible tests.
- Backup/restore drill, rollback rehearsal, release workflow, Kubernetes and ops assets: not exercised.
- Earlier slowness seen with Gemini (`REQUEST_DEADLINE_EXCEEDED`) matches defect 1 (valid SQL rejected, so a repair call consumed the 25 s budget). That causal link is inferred from the logs and from the two successful calls above; the original failing question was not replayed.

### How to start the verified application

```bash
# .env is required (copy .env.example and set both database passwords; LLM_PROVIDER=mock needs no key)
docker compose up --build -d
docker compose --profile demo run --rm seed      # demo data; refuses to run when APP_ENV=production
# Dashboard: http://localhost:3000     Readiness: http://localhost:3000/api/v1/health/ready
```

If you already have a stack from before this pass, rebuild so it picks up the fixes: `docker compose up --build -d` (database data is kept). Never add `--volumes` unless you mean to delete it.

### Run the tests

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest -m "not integration"
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check . && .venv/Scripts/python -m mypy
cd ../frontend && npm ci && npm run lint && npm test -- --run && npm run build
```

Integration tests need PostgreSQL with the `analytics_readonly` role (run `database/init/01-analytics-role.sql`), `alembic upgrade head`, the seed, `DATABASE_URL`, `ANALYTICS_DATABASE_URL`, `REDIS_URL`, and `REQUIRE_INTEGRATION=1`; see `.github/workflows/ci.yml`.

### Mock-provider demonstration

With `LLM_PROVIDER=mock`, the mock provider answers five questions deterministically: "What is the total number of active vehicles?", "What were the top 10 customers by revenue?", "Show monthly revenue for the last 12 months.", "Which vehicles had the highest idle time?", "Show fuel consumption by vehicle.". Ask them in the dashboard, or `POST /api/v1/analytics/ask` with `{"question": "..."}`.

### Simplification since this checkpoint

Dead code, the OpenAI provider, the SQL cache, OpenTelemetry tracing, the Redis rate limiter, the Kubernetes/release pipeline, the `static` auth mode, and the Playwright e2e suite have been removed, and `ask` / `execute` were split into smaller methods. The decisions behind each, and the items deliberately kept (metrics duplication, audit and feedback, direct SQL endpoints, evaluation and load-test tooling), are in `docs/Sequence.md` sections 18 and 19, and `docs/README.md` indexes the documentation. The section 22 results above describe the state before those changes; the closing verification is in Sequence.md section 19.

### Files to study next

`backend/app/services/generation.py` (orchestration and repair loop), `backend/app/analytics/validator.py`, `backend/app/analytics/service.py`, `backend/app/llm/prompt.py`, `backend/app/db/analytics_surface.py` with migration `b7c2d41f8a10`, `backend/app/core/auth.py`, `backend/app/core/rate_limit.py`, `backend/app/main.py`, `frontend/next.config.ts`, `frontend/components/analytics/analytics-dashboard.tsx`, and `docs/Sequence.md`.

### Checkpoint commit

Verified state: the commit titled `fix: stabilize analytics copilot baseline`, directly on top of `6ea3d59`. The results above were obtained on this change set as a working tree before it was committed.


## 23. Sprint 13: LangChain model boundary and explicit provider switching

**Status:** complete against the Sprint 13 checklist in `final_sprints.md`, with the limitations below.
**Base:** branch `main`, `HEAD` `5ea4878`, clean tree. All Sprint 13 changes are **uncommitted** in the working tree (by instruction); nothing was pushed.

### The path that was audited (13.1)

`/api/v1/analytics/generate` and `/ask` -> `SQLGenerationService` (`app/services/generation.py`) -> `provider.generate_sql` / `repair_sql` on a worker thread bounded by the request deadline -> `parse_llm_response` -> `AnalyticsQueryService.execute` (validate, read-only tenant-scoped transaction) -> result intelligence. The provider boundary was already small: one protocol (`app/llm/provider.py`), one factory function, two call sites in `generation.py`. Before this sprint three retry layers existed: the Google SDK (2 attempts on 5xx), the application repair loop, and the request deadline. The change surface was therefore bounded to `app/llm/`, settings, and wiring. Routes, the generation service, the validator and the executor were **not** changed.

### What changed

- **One factory, one provider class.** `app/llm/factory.py` selects the provider from `LLM_PROVIDER` and is the only place that constructs a client. `mock` returns the existing deterministic `MockLLMProvider`; `gemini` and `ollama` return `LangChainSQLProvider` (`app/llm/langchain_provider.py`) wrapping `ChatGoogleGenerativeAI` or `ChatOllama`. `gemini_provider.py` was removed.
- **Application-owned behaviour is unchanged in kind:** the prompt (`SQLPromptBuilder`), the response contract (`parse_llm_response`), bounded repair, and request-deadline handling stay in the application. LangChain does model invocation only. SQLGlot validation and read-only execution do not import LangChain.
- **Error classification** (`app/llm/errors.py`) walks the exception chain and maps to stable codes. New: `LLM_CREDENTIALS_INVALID` (previously an invalid key was a generic provider error). Provider text is never echoed.
- **One retry policy.** LangChain's own retries are off (its Gemini default is 6); `1 + LLM_MAX_RETRIES` attempts, transient infrastructure failures only, bounded by half the request deadline.
- **Settings renamed** to `LLM_PROVIDER` / `LLM_MODEL` (plus `OLLAMA_BASE_URL`, `LLM_MAX_RETRIES`). `LLM_MODE` and `GEMINI_MODEL` stop startup with a clear message instead of being ignored, and Compose forwards them so a stale `.env` is caught there too.
- **No fallback** between providers, by design and by test.
- **Default Gemini model** changed from `gemini-2.5-flash` to `gemini-3.6-flash` (see limitations).
- Dependencies: `google-genai` (direct) replaced by `langchain-core`, `langchain-google-genai`, `langchain-ollama`; `pytest` pinned to a patched release; `pip-audit` reports no known vulnerabilities.

Files: new `app/llm/{factory,langchain_provider,errors}.py`, `docs/llm-providers.md`, `tests/{test_llm_provider,test_llm_wire,test_llm_live}.py`; changed `app/core/{config,logging}.py`, `app/api/health.py`, `app/services/llm_dependencies.py`, `evals/{run_eval.py,thresholds.json}`, `pyproject.toml`, `docker-compose*.yml`, `.env.example`, CI and nightly workflows, the alert rule for configuration errors, and the docs; removed `app/llm/gemini_provider.py` and `tests/test_gemini_provider.py`.

### Verification (real results on the final code)

| Check | Result |
|---|---|
| `ruff check`, `ruff format --check`, `mypy` | Passed (64 source files) |
| Backend unit tests (`pytest -m "not integration"`) | 433 passed, 2 skipped (the opt-in live tests) |
| Same suite with all outbound network blocked | 433 passed, 2 skipped: no default test needs a network |
| Coverage gate | analytics 94.7%, services 95.5%, llm 96.5% |
| PostgreSQL integration tests (fresh database) | 43 passed, 0 skipped |
| Migrations up, down, up; read-only privilege check | Passed |
| Evaluation reference check; mock evaluation subset | 76 cases, 0 problems; 9-case subset, 5 scored, 5 correct, 0 of 4 adversarial leaks |
| Validator fuzz (default size) | 17 passed |
| `pip-audit` as CI runs it | No known vulnerabilities |
| Frontend lint, 122 tests, build, `tsc`; backend contract test (12) | Passed |
| Real Gemini client against a local server that always answers 503 | Server received exactly `1 + LLM_MAX_RETRIES` requests (1, 2, 3): no hidden retries |
| Docker stack, `LLM_PROVIDER=mock` | Healthy; KPI and bar results through the frontend proxy |
| Docker stack, `LLM_PROVIDER=ollama` with nothing running on the host | `LLM_PROVIDER_UNAVAILABLE` in about 1 s; `host.docker.internal` resolved inside the container; readiness stayed `ready`; no fallback |
| Docker stack with the owner's old `.env` (`LLM_MODE`, `GEMINI_MODEL` set) | Backend refused to start: "LLM_MODE is no longer supported; set LLM_PROVIDER instead." |
| Docker stack, bogus Gemini key | `LLM_CREDENTIALS_INVALID`, no key in the log |
| Docker stack, real Gemini key | See limitations: one request succeeded end to end (5 rows, pie chart); others hit Google capacity or rate limits and returned the correct classified errors |

Roadmap criteria and where they are proved: factory selection and invalid configuration (`test_llm_provider.py`); mock deterministic and offline (same file, and the network-blocked run); structured parsing and malformed output (same); provider errors, timeouts and retry exhaustion (`test_llm_provider.py`, `test_llm_wire.py`); `/generate` and `/ask` contracts (existing API and contract tests, unchanged); repair bounded and revalidated, security rejections never repaired, and dangerous SQL from any provider never executed (`test_llm_provider.py`, plus the existing security suite); tenant isolation and read-only permissions (the integration suite, unchanged).

### Limitations and things not verified

- **Ollama inference was not verified.** No Ollama is installed on this Windows machine. What is verified: the real `ChatOllama` client against a local fake server (reply parsed, malformed reply, model not pulled, server down), the unreachable-Ollama behaviour inside Docker, and the settings. Inference with a real model is for the owner to check on the Mac with `tests/test_llm_live.py` (see `docs/llm-providers.md`).
- **Live Gemini coverage is partial.** On four models (`gemini-3.6-flash`, `gemini-3.8-flash`, `gemini-3.1-flash-lite`, `gemini-flash-lite-latest`) the provider returned structured JSON that the validator accepted. Through the full stack one request succeeded. Other requests failed because of Google: HTTP 503 "high demand" (also seen for `gemini-3.5-flash` and `gemini-flash-latest`), then HTTP 429 once the key's quota was used up by this testing. Those failures are the correct classified errors; they do not show the new code failing. The earlier slow `REQUEST_DEADLINE_EXCEEDED` requests are consistent with the same capacity problem.
- **The old default model is retired.** `gemini-2.5-flash` now returns 404 "no longer available to new users" for this key. The default became `gemini-3.6-flash` because it worked here; model ids retire, so set `LLM_MODEL` explicitly.
- **Gemini 3 ignores `temperature`.** Only the mock is deterministic; compare real models over repeated runs.
- **The owner's `.env` must be updated** before the stack will start: rename `LLM_MODE` to `LLM_PROVIDER` and `GEMINI_MODEL` to `LLM_MODEL` (and pick an available model).
- `langsmith` is installed transitively and would auto-trace the model call if `LANGSMITH_TRACING` were set. Sprint 14 (section 24) added sanitized, opt-in tracing and switches LangChain's own tracing off around every model call.
- Not run: the k6 load test, Trivy scans, the CI workflows on a real runner (their YAML parses), and a live Ollama or LangSmith check.


## 24. Sprint 14: Ollama, optional LangSmith tracing, cross-provider evaluation

**Status:** complete against the Sprint 14 checklist for everything that can be verified on this machine. Two things cannot be and are recorded as not run: inference with a real Ollama model, and a live Gemini evaluation (see limitations).
**Base:** branch `main`, `HEAD` `19213a2` (Sprint 13, committed by the owner). All Sprint 14 changes are **uncommitted** in the working tree, by instruction; nothing was pushed.

### 14.1 Ollama

The factory branch already existed from Sprint 13. Added: `scripts/llm_smoke.py` (provider builds, model answers and the reply parses, SQL validates, and with PostgreSQL configured it executes read-only; exit 0 only if every step that ran passed); a macOS setup guide with a pulled-by-hand starter model (`qwen2.5-coder:7b`, 4.7 GB per the Ollama library; `llama3.1:8b` 4.9 GB and `qwen2.5-coder:14b` 9.0 GB as alternatives; labelled a suggestion, not a measured recommendation); Docker-to-host networking and troubleshooting in `docs/llm-providers.md`. The default address changed from `localhost` to `127.0.0.1`: `localhost` resolves to both `127.0.0.1` and `::1`, which cost an extra connection attempt against a loopback-only server (0.32 s versus 0.10 s with curl). Ollama is not a Compose dependency, nothing downloads a model, and a stopped Ollama fails in about a second with `LLM_PROVIDER_UNAVAILABLE`.

Verified here: the real `ChatOllama` client against a local stand-in (reply parsed, malformed reply, model not pulled, server down: `tests/test_llm_wire.py`); the smoke script against the stand-in; and, in an isolated Compose stack, a container reaching a **loopback-bound** stand-in on the host through `host.docker.internal` and answering a question end to end (KPI 766, readiness `ready`, the stand-in logged the requests). Not verified: **inference with a real model**, which is for the owner to run on the Mac (commands in `docs/llm-providers.md`).

### 14.2 LangSmith tracing (optional, off by default)

`app/core/llm_tracing.py`. Findings that shaped it, all measured: with `LANGSMITH_TRACING=true` LangChain auto-traces the model call and the run would carry the prompt; and against an unreachable endpoint LangSmith's default client let the process exit only after 45 s (8 s even with tight timeouts), while its synchronous mode blocks the request. So tracing builds its own sanitized runs and hands them to a bounded in-process queue (non-blocking put); a daemon worker exports with short timeouts, no retries and a circuit breaker; shutdown waits about a second. Runs have empty inputs and carry only an allowlist of short tokens and numbers (request id, operation, provider, model, outcome, error code, attempt and repair counts, row and table counts, case id, duration). Errors are recorded as codes, never messages. LangChain's automatic tracing is suspended around every model call. Stages: operation, context retrieval, prompt construction, model invocation (per attempt), response parsing, SQL validation, repair, execution.

Evidence: 31 tests in `tests/test_llm_tracing.py`, including a request made with deliberately sensitive content and a check that none of it appears in anything exported; the real LangSmith client against a LangSmith-shaped local server, reading the actual bytes sent; a control showing an unprotected client *does* send the question and ours does not; a failing client, a slow client (5 requests in under 2 s while exports blocked), a circuit breaker, and a subprocess exit-time test against a dead endpoint. In Docker: with tracing on and a stand-in LangSmith, 7 runs were received, every `inputs` was `{}`, and the sensitive question, SQL, table names, row value and key were all absent from every byte; with the stand-in killed, three requests still answered in 0.03 to 0.12 s and the container stopped in 0.8 s; with the flag off but a key and endpoint set, zero requests were sent. No live LangSmith check was run.

### 14.3 Evaluation

Dataset facts (counted from the file): 76 cases = 58 accuracy + 6 structure + 12 adversarial; a full run scores 64 and reports 12 adversarial separately; the mock subset is 9 cases = 5 scored + 4 adversarial. Two defects found in the harness and fixed: (1) an adversarial case counted as "rejected, passed" whenever the request raised *any* error, so a provider outage would have looked like a safety success; such cases are now **inconclusive** (the safety layers never saw them), and only a rejection by the validator or executor counts; (2) the mock refuses all four of its adversarial cases itself, so the earlier "4 rejected, 0 leaks" said nothing about the validator. The report now states: dataset size, cases run, not run, scored; valid-SQL rate versus correctness (and correctness among answers produced); provider errors, parse failures, deadlines, safety rejections, execution errors, declines; repairs; mean/p50/p95 latency; provider and model; the settings that shape answers; the machine; and, for Ollama, its version and loaded-model memory. A run where every request fails in the model path is `status: blocked` with exit code 3; configuration errors exit 2 with a message instead of a traceback. `--model` sets the model for a run. Thresholds were not invented: the Ollama section is unset like Gemini's, to be set from a baseline.

Reports actually produced here: **mock** (deterministic subset): 9 of 76 cases run (67 not run), 5 of 5 scored correct, 0 of 4 adversarial leaks, 4 adversarial inconclusive (declined by the mock), p95 64 ms, on Windows 10, 8 CPUs, 31.7 GB, PostgreSQL 16. **Ollama with nothing running:** `status: blocked`, exit 3 (this verified the blocked path; it is not a result). **Gemini:** not run; the owner's `.env` key is empty and the earlier key had exhausted its quota. The baseline table in `docs/evaluation.md` records all three honestly.

### 14.4 Reliability

Added `analytics_llm_retries_total{provider}`. Existing metrics already cover provider, duration, outcome (`analytics_llm_errors_total{code}`) and repair counts; logs carry `llm_provider`, `llm_model`, `error_code` and `attempt` and no content. One retry policy and no fallback are unchanged from Sprint 13.

### Verification (final code)

| Check | Result |
|---|---|
| `ruff check`, `ruff format --check`, `mypy` | Passed (65 source files) |
| Backend unit tests | 470 passed, 2 skipped (opt-in live tests) |
| Same suite with outbound network blocked | 470 passed, 2 skipped |
| Coverage gate | analytics 94.7%, services 95.8%, llm 96.6% |
| PostgreSQL integration tests, migration round trip, privilege check | 43 passed; down 2 / up 2; verified |
| Evaluation reference check; mock subset exit code | 76 cases, 0 problems; exit 0 |
| Validator fuzz at the nightly size (20,000) | 17 passed |
| `pip-audit` as CI runs it | No known vulnerabilities |
| Frontend lint, 122 tests, build, `tsc` | Passed |
| Docker, `LLM_PROVIDER=mock` (final code) | Healthy; KPI 766 and a bar chart; readiness `ready`; tracing flag `false` |

### Limitations

- **No inference with a real Ollama model was run** (no Ollama on this machine). The Mac verification is the remaining Ollama step.
- **No live Gemini evaluation** (no key available), and **no live LangSmith check**. Both are reported as not run, not as passed.
- The Gemini and Ollama evaluation baselines and thresholds do not exist yet; the first live runs create them.
- Tracing sends request ids and timings to a third party when enabled; the data flow is documented in `docs/llm-providers.md`, `docs/security.md` and `docs/threat-model.md`.
- Gemini 3 ignores `temperature`; real-model results are not deterministic.

**Exit gate:** configuration switches among mock, Gemini and Ollama (mock and Ollama exercised in Docker here, Gemini in Sprint 13); tracing cannot break a core request (shown with a dead, slow and failing endpoint); and honest evaluation reports exist, with the live ones recorded as blocked or not run.


## 25. Sprint 15: final hardening and closeout

Sprint 15 added no features. It verified the whole system, wrote the missing security-invariant tests, reconciled the documents with the code, and recorded the final state.

### Baseline and final state

- Branch `main`, HEAD `b1e07c2` (Sprint 14). The tree was clean when Sprint 15 started.
- Sprint 15 changes are **uncommitted** by the owner's instruction: `.env.example`, `README.md`, `docs/README.md`, `docs/architecture.md`, `docs/deployment.md`, `docs/operations.md`, `final_sprints.md`, `progress.md`, and the new `backend/tests/test_security_invariants.py`. The checkpoint exists when the owner commits these.
- No application code changed in Sprint 15. The only code-adjacent addition is the invariants test file.

### 15.1 Verification record (final tree)

| Check | Result |
|---|---|
| `ruff check`, `ruff format --check`, `mypy` (65 source files) | Clean |
| Backend unit suite (`-m "not integration"`) | 497 passed, 2 skipped (the live-provider tests, which need a key) |
| Same suite in a brand-new virtual environment | 497 passed, 2 skipped; `pip check` clean |
| Coverage gates (analytics, services, llm) | 94.7%, 95.8%, 96.6% |
| PostgreSQL integration tests (`REQUIRE_INTEGRATION=1`) | 43 passed |
| Migration round trip, read-only role privilege check | Down 2 / up 2; verified |
| Evaluation reference check | 76 cases, 0 problems |
| Mock evaluation subset | Exit 0 |
| Validator fuzz at the nightly size (20,000) | 17 passed |
| `pip-audit` as CI runs it | No known vulnerabilities |
| Frontend lint, 122 tests, build, `tsc` | Passed |
| `npm audit`, `npm ci --dry-run` | 0 vulnerabilities; exit 0 |
| Backend contract test | 12 passed |
| Workflow, Compose and Prometheus YAML (10 files) | Parse |
| `docker compose config` (base, dev, loadtest) | Valid |
| Markdown link check (30 files) | 0 broken |
| Settings completeness (every `Settings` alias documented) | Complete |

### 15.2 Security invariants and their evidence

| # | Invariant | Evidence |
|---|---|---|
| 1 | The model layer cannot reach the database | `test_the_model_layer_cannot_reach_the_database` (AST scan of `app/llm` and `app/core/llm_tracing.py`) |
| 2 | The SQL safety layer does not depend on LangChain or the model layer | `test_the_sql_safety_layer_does_not_depend_on_langchain_or_the_model_layer` |
| 3 | Forbidden SQL never opens a database connection | `test_forbidden_sql_never_opens_a_database_connection` (9 statements, protocol stub and LangChain provider; `engine.connect` replaced by a guard that fails the test) |
| 4 | A repaired statement is validated before it can run | `test_a_repaired_statement_is_validated_before_it_can_run`; security errors are never repaired |
| 5 | The provider cannot change who the query runs as | `test_the_provider_cannot_change_who_the_query_runs_as`; live check: customer 7 sees 4 of 766 vehicles, customer 8 sees 11 |
| 6 | A provider failure leaks no key, message or request | `test_a_provider_failure_does_not_leak_its_message_key_or_request_into_the_response_or_logs` (deliberately fake key) |
| 7 | Production error responses do not echo SQL or driver messages | `test_production_error_responses_do_not_echo_the_sql_or_the_driver_message` |
| 8 | Outside production only the generation failure carries a debug block | `test_outside_production_only_the_generation_failure_carries_a_debug_block` (known, documented behavior) |
| 9 | Tracing cannot break a request and sends no prompts, SQL or secrets | `test_llm_tracing.py` (dead, slow and failing endpoint; leak-detection control) |
| 10 | No automatic provider fallback | `test_an_unknown_provider_fails_validation_and_never_falls_back` in `test_llm_provider.py`; live: Ollama selected with nothing running gives 503 `LLM_PROVIDER_UNAVAILABLE` in 0.9 s and never switches |
| 11 | Secrets are absent from Git, logs and images | Git history search for the earlier key (0 hits); only key-shaped string in the repository is the fake test value; backend log after about 40 mixed requests (62 lines) had no token, secret, question or SQL; frontend container environment and bundle clean |

### 15.3 End-to-end walkthrough (Docker, project `copilot-verify`, isolated ports and volumes)

- Mock provider with JWT authentication: stack healthy, readiness `ready`, walkthrough script 18/18, tenant and JWT script 19/19.
- Provider failure: Ollama selected with nothing running returned 503 `LLM_PROVIDER_UNAVAILABLE`; readiness stayed `ready` because readiness does not call the provider.
- Forbidden SQL: a stand-in Ollama server returned 10 hostile statements (DROP, DELETE, UPDATE, a PII column, `pg_shadow`, `public.customers`, multiple statements, `pg_sleep`, `current_setting`, an unknown table). All were rejected (`QUERY_SECURITY_ERROR` or `QUERY_GENERATION_FAILED`); the database was unchanged afterwards (16 tables; 1000, 100, 354 and 50000 rows in the checked tables) and a valid control question returned 200.
- Gemini selected with no key: readiness `degraded: ["llm_provider"]` and requests fail with `LLM_CONFIGURATION_ERROR`.
- `backend/scripts/llm_smoke.py`: passes for mock and for the stand-in Ollama with real PostgreSQL execution; exits 2 for Gemini without a key.
- The temporary stack, volumes, stand-in servers and test secrets were removed. The owner's own PostgreSQL volume and containers were not touched.

### 15.4 Documentation reconciliation

Most of `progress.md` (the overview, architecture, feature, testing, roadmap and state sections) was rewritten to match the code; earlier sprint blocks that describe removed features are labelled historical. `README.md` gained the provider-switching snippet and corrected durability, limitation and out-of-scope text. `docs/deployment.md` dropped the removed `LLM_MODE` instructions. `docs/architecture.md` describes the single-instance state model. `docs/operations.md` has a model-provider operations section. `.env.example` explains the Compose defaults against running directly. `final_sprints.md` is marked completed. A final audit then brought `docs/production-security-review.md`, `docs/conversation-context.md`, `docs/security.md` (conversation expiry), `docs/runbooks/credential-rotation.md` (LangSmith key) and `frontend/README.md` (was the create-next-app boilerplate) in line with the code.

### 15.5 Repository hygiene

No secrets, machine paths or build artifacts are tracked. The README documents the Windows long-path requirement for installing the Gemini client library. Temporary files were kept in the session scratchpad, not in the repository.

### Providers and evaluation: what was and was not run

| Item | Status |
|---|---|
| Mock provider | Fully exercised (tests, Docker, evaluation subset: 9 of 76 cases; 5 of 5 scored cases correct, 0 of 4 adversarial cases leaked, 4 inconclusive) |
| Ollama | Code path and failure handling verified against a **stand-in server** only; **no real model inference was run** |
| Gemini | Verified in Sprint 13; in Sprint 15 only the no-key and configuration paths. **No live Gemini evaluation was run** |
| LangSmith | Verified against local fake endpoints only; **no live check** |
| k6 load test, Trivy scan | Not run |
| First CI run on GitHub | Not run |

### Remaining limitations

- Gemini and Ollama evaluation baselines do not exist; the first live runs create them. Real-model results are not deterministic (Gemini 3 ignores `temperature`).
- The backend has no lockfile; `pip-audit` covers the resolved set at the time it runs.
- Tracing, when enabled, sends request ids and timings to a third party (documented in `docs/llm-providers.md`, `docs/security.md`, `docs/threat-model.md`).
- Outside production the generation-failure response includes a `debug` block by design.
- Out of scope: an identity provider, multi-replica scale-out, multi-region operation, embeddings, automatic provider fallback.

### Commands

```bash
# Run locally with the stack (mock provider, no key)
docker compose up --build -d
docker compose --profile demo run --rm seed

# Switch provider: set LLM_PROVIDER (mock | gemini | ollama) and LLM_MODEL in .env, then
docker compose up -d --build
python backend/scripts/llm_smoke.py

# Verify
cd backend && python -m ruff check . && python -m mypy && python -m pytest -m "not integration"
cd frontend && npm run lint && npm test && npm run build
```

### Project-closure gate

The exit conditions of `final_sprints.md` are met except for the checks that need resources not available here, listed above as not run. Those are verification steps for the owner (a real Ollama run on the Mac, a live Gemini evaluation if a key is supplied, and the first GitHub CI run), not further development. The project is closed.
