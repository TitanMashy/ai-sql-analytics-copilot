# AI SQL Analytics Copilot: Project Handoff

This document is the persistent context for future coding agents. Read it before changing the repository. The repository and its tests are the source of truth; this document is a handoff summary, not a replacement for inspecting the code.

## 1. Project Overview

**AI SQL Analytics Copilot** is a backend-first analytics product for fleet-management SaaS data. A user asks a natural-language business question, such as "What were the top customers by revenue?", and the system retrieves relevant schema context, generates read-only PostgreSQL SQL, validates it independently of the LLM, executes it against a restricted analytics database, and presents result intelligence in a conversational dashboard.

The target users are fleet operators, business analysts, and product/revenue teams who need answers from operational, utilization, maintenance, fuel, and billing data without hand-writing SQL. The project exists to make that workflow explainable and safer than allowing an LLM to execute arbitrary database output.

The technically interesting parts are the modular LLM provider boundary, deterministic schema/business-context retrieval, AST-backed SQL security, a separate PostgreSQL read-only role, bounded SQL repair, bounded conversation context, and post-query KPI/visualization analysis.

## 2. Current Status

```text
Current status: Sprints 1–12 implemented. The backend, frontend and Docker Compose stack were run and
verified in the stabilization pass (section 22), with the exceptions listed there under "Not run".
```

| Sprint | Status | Description |
|---|---|---|
| Sprint 1 | COMPLETE | Repository foundation, FastAPI startup, configuration, logging, SQLAlchemy sessions, PostgreSQL Compose setup, tests, and developer tooling. |
| Sprint 2 | COMPLETE | Fleet-management PostgreSQL schema, Alembic migration, realistic deterministic seed data, indexes, schema metadata, and read-only analytics role. |
| Sprint 3 | COMPLETE | Analytics query/validation API, read-only execution service, result normalization, schema APIs, limits, timeouts, request IDs, and structured errors/logging. |
| Sprint 4 | COMPLETE | Natural-language SQL generation, schema retrieval, business definitions, provider abstraction, mock provider, Gemini provider, `/generate`, `/ask`, response parsing, and bounded repair. |
| Sprint 5 | COMPLETE | SQLGlot AST validation, table/column allowlists, dangerous-function/system-table protection, complexity rules, normalized SQL, repair security, and security tests/docs. |
| Sprint 6 | COMPLETE | Result analyzer, KPI detection, deterministic visualization selection/validation, summaries, data-quality warnings, frontend-ready `/ask` responses, and visualization documentation. |
| Sprint 7 | COMPLETE | Bounded in-memory conversation context, follow-up-aware SQL generation, and conversation endpoints. |
| Sprint 8 | COMPLETE | Responsive Next.js dashboard, typed API integration, charts/results, Docker service, and frontend validation. |
| Sprint 9 | COMPLETE | Production configuration, API limits/rate controls, metrics, health/readiness, provider reliability, frontend failure handling, deployment docs, and CI. |
| Sprint 10 | COMPLETE | Final project documentation, portfolio narrative, verified handoff, and repository readiness. |
| Sprint 11 | IMPLEMENTED, VERIFIED IN STABILIZATION PASS | Security hardening and correctness: narrowed proxy, JWT auth, per-principal limits, PII-free tenant-scoped analytics views, function allowlist, LIMIT enforcement, SQLSTATE errors and repair hints, request deadline, prompt/retrieval fixes, result-intelligence fixes. Executed for the first time in the stabilization pass (section 22), which found and fixed the defects listed there. |

Recent implementation commits include Sprint 7 `9554013`, Sprint 8 `5639dd7`, and Sprint 9 `e1291e4`. The Sprint 10 documentation updates are intentionally uncommitted.

## 3. Product Capabilities

Implemented capabilities:

- FastAPI modular monolith with health, schema, SQL, generation, and combined analytics endpoints.
- PostgreSQL fleet-management dataset with deterministic demo seed data.
- Schema-aware retrieval based on table/column/business terminology.
- Business metric definitions for revenue, active vehicles, completed trips, fuel cost, idle time, and payments.
- Gemini provider using the official `google-genai` SDK and structured JSON output.
- Deterministic mock provider for development and CI without an API key.
- Shared provider interface with Gemini and the deterministic mock provider (the legacy OpenAI provider was removed).
- PostgreSQL AST parsing and security validation with SQLGlot.
- Explicit application-table allowlist and practical column/alias validation.
- Read-only analytics database role and permission verification.
- Bounded SQL repair that re-enters the exact same validator.
- Result normalization for JSON-safe values.
- KPI detection for single aggregate results.
- Deterministic `table`, `kpi`, `bar`, `line`, and `pie` visualization metadata.
- Visualization field validation and table fallback.
- Deterministic grounded summaries, empty-result handling, NULL warnings, and configurable summary enablement.
- Structured JSON logs with request ID, endpoint, validation status, execution time, row count, and status code.
- Production settings for environment/debug/docs, secret masking, exact CORS origins, validated pool/provider/request/rate-limit configuration.
- Configurable request-body, question, conversation-context, turn, and SQL size limits.
- Process-local sliding-window throttling with structured 429 responses for generation, ask, conversation creation, and turn append.
- Configurable PostgreSQL pools with pre-ping, recycle, checkout/connect timeouts, and per-process shared engines.
- Request-correlated structured errors, safe response/security headers, health/readiness routes, and process-local JSON metrics.
- Gemini timeout, bounded exponential retries for transient 5xx responses, and explicit rate-limit/model/timeout/malformed-response classification.
- Bounded repair metrics and tests confirming timeouts/security/provider failures do not proceed through unsafe repair/execution.
- Next.js timeout/network error codes, runtime result validation, retry and duplicate-submit handling, and chart/application error boundaries.
- Non-root production Docker images, distinct PostgreSQL owner/read-only credentials for fresh clusters, Compose health checks, deployment/security docs, and GitHub Actions CI.

Known limitations and optional improvements are listed in Section 16. These are not implemented and are not part of the completed sprint scope.

## 4. Architecture

```text
User / API Client
        |
        v
FastAPI Query API
        |
        v
SchemaRetriever + Business Definitions
        |
        v
LLMProvider (Gemini or Mock)
        |
        v
Structured SQL Response
        |
        v
SQLGlot AST Validation + Security Rules
        |
        v
AnalyticsQueryService
        |
        v
PostgreSQL analytics_readonly
        |
        v
Result Normalization + Column Profiling
        |
        +--> KPI Detection
        +--> VisualizationSelector
        +--> Grounded Summary
        |
        v
Frontend-ready Analytics Response
        |
        v
Next.js dashboard (conversation, KPI, chart, table, SQL)
```

Responsibilities:

- **FastAPI/API layer:** validates request bodies, attaches request IDs, exposes OpenAPI routes, and maps internal errors to structured responses. It does not execute SQL directly.
- **SchemaRetriever:** selects relevant application tables and business definitions using deterministic keyword/column relevance. It is ready for a future embedding implementation but has no vector database.
- **LLMProvider:** abstracts SQL generation and repair. `GeminiProvider` is the configured real provider; `MockLLMProvider` supplies deterministic queries for tests and demos.
- **SQLGenerationService:** coordinates question, schema context, provider output, bounded repair, and the existing analytics execution service. Generated SQL is never treated as trusted.
- **SQLValidator:** parses and validates PostgreSQL SQL before execution.
- **AnalyticsQueryService:** uses `ANALYTICS_DATABASE_URL`, applies PostgreSQL statement timeout, executes normalized SQL, enforces result limits, classifies database errors, and normalizes rows.
- **Result intelligence services:** run only after successful execution and cannot influence SQL generation or execution.
- **Next.js frontend:** sends typed requests through a same-origin rewrite to FastAPI and renders returned data. It does not generate SQL or make validation, allowlist, metric, or visualization decisions.
- **PostgreSQL:** the application/migration owner uses `DATABASE_URL`; generated analytics queries use the separate `analytics_readonly` role through `ANALYTICS_DATABASE_URL`.

## 5. Technology Stack

### Backend

- Python 3.12+ (the development environment used Python 3.13)
- FastAPI and Uvicorn
- Pydantic v2 and `pydantic-settings`
- SQLAlchemy 2.x and psycopg 3
- SQLGlot for PostgreSQL AST parsing
- Google `google-genai` SDK for Gemini
- pytest and Ruff

### Database

- PostgreSQL 16 via Docker Compose
- Alembic migration system
- SQLAlchemy declarative models
- Main tables: `customers`, `users`, `vehicles`, `drivers`, `trips`, `vehicle_locations`, `fuel_records`, `maintenance_records`, `invoices`, `payments`, and `subscriptions`
- Internal `seed_runs` table makes seeding idempotent

### AI

- `LLMProvider` protocol in `backend/app/llm/provider.py`
- `GeminiProvider` in `backend/app/llm/gemini_provider.py`
- `MockLLMProvider` in `backend/app/llm/mock_provider.py`
- Structured prompt and parser modules
- Real provider selection is controlled by `LLM_MODE`; the example mode is `mock`. Production mode rejects mock mode and requires a configured real provider. Never copy secrets from local environment files into documentation or commits.

### Frontend

- Next.js 16, React 19, TypeScript, Tailwind CSS, Recharts, Lucide React, Vitest, Testing Library, and jsdom.
- `frontend/components/layout/app-sidebar.tsx`: workspace shell and switchable conversation list.
- `frontend/components/analytics/question-composer.tsx`: accessible question input and starter prompts.
- `frontend/components/analytics/analytics-results.tsx`: summary, KPIs, charts, data table, warnings, and collapsible/copyable SQL.
- `frontend/components/charts/chart-renderer.tsx`: backend-selected bar, line, area, and pie rendering.
- `frontend/lib/api.ts`: typed API client; backend failures remain visible and are never replaced with fake results.
- Next.js rewrites proxy `/api/*` to `INTERNAL_API_URL` (default `http://localhost:8000`) to keep browser requests same-origin without changing backend CORS policy.

### Infrastructure

- Docker Compose services: `postgres`, `backend`, and `frontend`; health gates are PostgreSQL -> backend -> frontend.
- Backend Docker image installs runtime dependencies only, runs as non-root, and uses a read-only root filesystem in Compose.
- Frontend uses the standalone Next.js output and non-root runtime.
- GitHub Actions runs backend lint/tests, frontend lint/tests/build, and Compose configuration validation without Gemini credentials.
- `.env.example` documents configuration; `.env` is ignored and must never be committed.
- Make targets include `dev`, `test`, `lint`, `format`, `migrate`, `seed`, `verify-permissions`, `docker-up`, and `docker-down`.

## 6. LLM Architecture

The provider interface defines:

- `generate_sql(question, schema_context, conversation_context=None)`
- `repair_sql(question, original_sql, error_message, schema_context)`

`GeminiProvider`:

- Reads `GEMINI_API_KEY` and `GEMINI_MODEL` from settings.
- Uses the official Google Gemini SDK.
- Sends the SQL prompt with `response_mime_type="application/json"` and the shared structured response schema.
- Parses response text through `parse_llm_response`; malformed or empty output becomes a controlled `LLMProviderError`.
- Uses the same provider path for repair prompts.
- Does not execute SQL.

`MockLLMProvider`:

- Is deterministic and supports representative active-vehicle, revenue, monthly-revenue, idle-time, and fuel questions.
- Is required for tests, CI, and credential-free local demos.
- Must be preserved when adding or changing providers.

Provider selection lives in `app/services/llm_dependencies.py`. Adding another provider should require a new implementation plus a configuration branch, not changes to API routes, schema retrieval, SQL validation, or query execution.

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
GeminiProvider or MockLLMProvider
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

The LLM is **not** a trusted security boundary. The SQL parser, application allowlist, execution limits, and PostgreSQL permissions are the actual defense layers.

Current controls:

- SQLGlot parses using PostgreSQL syntax before execution.
- Only one read-only `SELECT`/read-only set operation is allowed; safe CTEs are supported.
- Rejects `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`, `REVOKE`, `COMMENT`, transaction operations, `SELECT INTO`, and row locks.
- Rejects multiple statements.
- Explicitly allowlists the eleven application analytics tables.
- Protects `pg_catalog`, `information_schema`, `pg_toast`, and `pg_*` references.
- Denies dangerous functions such as file access, `dblink`, command-related functions, and `pg_sleep`.
- Validates aliases and known columns where practical.
- Controls joins, nesting, cartesian joins, literal LIMIT values, result row counts, and PostgreSQL statement timeout.
- Normalizes SQL before execution and returns detailed validation metadata.
- Uses the separate `analytics_readonly` PostgreSQL role.
- Repair retries are bounded by `MAX_REPAIR_RETRIES`; security, permission, timeout, complexity, and result-limit failures are not automatically repaired.
- Request and database errors return structured codes without database stack traces to clients.

Known security limitations: there is no tenant-level authorization layer, no cost-based planner or EXPLAIN budget, and AST validation is defense in depth rather than a complete guarantee. Future work may add database views, network isolation, stricter tenant policies, and query-cost controls. Do not weaken the existing validator or database role to make a generated query work.

## 9. Database

PostgreSQL is created by `docker-compose.yml`. Alembic owns schema creation; do not replace migrations with `Base.metadata.create_all()` in application startup.

The initial revision is `9a999e64b310_create_initial_analytics_schema.py`. The schema has foreign keys, status/value/date checks, unique identifiers, and analytics-oriented indexes on foreign keys, time fields, statuses, and tenant/time combinations.

The deterministic seed in `backend/app/db/seed.py` uses seed `20260923`, covers 2024–2025, and is protected by `seed_runs`:

- 100 customers
- 354 users in the verified run
- 1,000 vehicles
- 500 drivers
- 50,000 trips
- 20,000 vehicle locations
- 20,000 fuel records
- 10,000 maintenance records
- 10,000 invoices
- 20,000 payments
- 100 subscriptions

The `app` role owns/migrates the schema. `analytics_readonly` receives database connection, schema usage, and SELECT privileges only. `database/verify-readonly.sql` checks SELECT and rejects write/schema privileges; `make verify-permissions` runs it inside Compose. The analytics service must always use `ANALYTICS_DATABASE_URL`, never the application owner URL.

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
- `ResultSummaryService` produces deterministic grounded summaries from returned data only. `ENABLE_RESULT_SUMMARY=false` disables them. A Gemini summary callback exists as an isolated extension point, but the default dependency wiring currently uses deterministic summaries and does not make an extra Gemini call.

## 11. API Surface

All routes are under `/api/v1` unless noted.

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Dependency-free liveness probe. |
| GET | `/health/ready` | Checks application DB, analytics DB, and selected provider configuration. |
| GET | `/api/v1/health` | Checks application database connectivity. |
| GET | `/api/v1/health/ready` | Versioned readiness alias. |
| GET | `/api/v1/metrics` | Process-local counters and latency averages; restrict at the network boundary. |
| POST | `/api/v1/analytics/query` | Validates and executes direct read-only SQL. Request: `{ "sql": "..." }`. Response: columns, rows, row count, execution time. |
| POST | `/api/v1/analytics/validate` | Returns normalized SQL, errors, warnings, referenced tables, and complexity metadata without executing. |
| POST | `/api/v1/analytics/generate` | Converts `{ "question": "..." }` into structured SQL without execution. Returns question, SQL, explanation, tables, schema context, provider, and confidence. |
| POST | `/api/v1/analytics/ask` | Generates SQL, validates/executes it, and returns SQL results plus summary, KPI, visualization, and warnings. |
| GET | `/api/v1/schema` | Returns all non-secret schema metadata. |
| GET | `/api/v1/schema/tables` | Lists available analytics table names. |
| GET | `/api/v1/schema/tables/{table_name}` | Returns one table's columns and relationships. |
| GET | `/docs` | FastAPI interactive OpenAPI documentation. |

Structured errors use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`. Codes include validation, parse, security, permission, timeout, table-not-found, provider, invalid-request, request-too-large, and rate-limit errors.

## 12. Repository Structure

```text
ai-sql-analytics-copilot/
├── backend/
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/9a999e64b310_create_initial_analytics_schema.py
│   ├── app/
│   │   ├── analytics/       # query execution, AST validation, normalization
│   │   ├── api/             # FastAPI route modules
│   │   ├── core/            # settings, metrics, middleware, telemetry, logging
│   │   ├── db/              # engines, ORM base, seed, schema metadata
│   │   ├── llm/             # provider interface, Gemini, mock, parser, prompts
│   │   ├── models/           # SQLAlchemy entities
│   │   ├── schemas/          # Pydantic API contracts
│   │   ├── services/         # retrieval, generation, result intelligence
│   │   └── main.py
│   ├── tests/               # API, database, Gemini, security, result tests
│   ├── Dockerfile
│   └── pyproject.toml
├── database/
│   ├── init/01-analytics-role.sql
│   └── verify-readonly.sql
├── docs/
│   ├── architecture.md
│   ├── business-definitions.md
│   ├── database-schema.md
│   ├── deployment.md
│   ├── production-security-review.md
│   ├── security.md
│   └── visualization.md
├── .github/workflows/ci.yml
├── frontend/                # Next.js dashboard and tests
├── .env.example
├── docker-compose.yml
├── Makefile
├── README.md
└── progress.md
```

## 13. Environment Variables

Values below are documented formats only. Real values belong in ignored `.env`, never in this file or Git.

| Variable | Required | Purpose / example |
|---|---|---|
| `APP_ENV` | No; default `development` | `development`, `test`, or `production`; production rejects SQLite and mock mode. |
| `DEBUG` | No; default `false` | Framework debug; always effectively disabled in production. |
| `CORS_ALLOWED_ORIGINS` | No; default `[]` | JSON array of exact origins; credentials are not enabled. |
| `DATABASE_URL` | Runtime/app DB | Migration and owner connection; production must use PostgreSQL. |
| `ANALYTICS_DATABASE_URL` | Analytics execution | Restricted read-only PostgreSQL connection, separate from the owner URL. |
| `POSTGRES_PASSWORD` | Fresh Compose database | Owner role password; supply at runtime only. |
| `ANALYTICS_DATABASE_PASSWORD` | Fresh Compose database | Distinct read-only role password; supply at runtime only. |
| `GEMINI_API_KEY` | Only when `LLM_MODE=gemini` | Google Gemini credential; never print or commit it. |
| `GEMINI_MODEL` | No; default `gemini-2.5-flash` | Gemini model name. |
| `LLM_MODE` | No; default `mock` | `mock` or `gemini`; mock is disabled in production. |
| `LOG_LEVEL` | No; default `INFO` | Structured application log threshold. |
| `LLM_TIMEOUT_SECONDS` | No; default `30` | Provider timeout; transient Gemini 5xx retries are bounded. |
| `DATABASE_POOL_SIZE` | No; default `5` | SQLAlchemy pool size per engine. |
| `DATABASE_MAX_OVERFLOW` | No; default `10` | Connections above pool size. |
| `DATABASE_POOL_TIMEOUT_SECONDS` | No; default `5` | Pool checkout timeout. |
| `DATABASE_POOL_RECYCLE_SECONDS` | No; default `1800` | Connection recycle interval. |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | No; default `5` | PostgreSQL connect timeout. |
| `MAX_RESULT_ROWS` | No; default `1000` | Maximum rows fetched/returned by analytics execution. |
| `QUERY_TIMEOUT_SECONDS` | No; default `10` | PostgreSQL statement timeout. |
| `MAX_QUERY_JOINS` | No; default `5` | AST complexity threshold. |
| `MAX_QUERY_NESTING` | No; default `3` | AST nesting threshold. |
| `MAX_REPAIR_RETRIES` | No; default `3` | Maximum repair attempts for repairable query errors. |
| `ENABLE_RESULT_SUMMARY` | No; default `true` | Enables deterministic post-query summaries. |
| `MAX_QUESTION_LENGTH` | No; default `2000` | Maximum natural-language question length. |
| `MAX_CONVERSATION_CONTEXT_CHARS` | No; default `2000` | Maximum caller context or conversation turn length. |
| `MAX_REQUEST_BODY_BYTES` | No; default `16384` | Maximum fully buffered request body; capped at 1 MiB. |
| `RATE_LIMIT_ENABLED` | No; default `true` | Enable in-process sliding-window limits. |
| `RATE_LIMIT_REQUESTS` | No; default `30` | Requests allowed per endpoint/client window. |
| `RATE_LIMIT_WINDOW_SECONDS` | No; default `60` | Sliding window duration. |

The legacy OpenAI provider and its `OPENAI_API_KEY` / `OPENAI_MODEL` settings were removed; Gemini and the deterministic mock are the only providers.

## 14. Testing

Tests live in `backend/tests` and use pytest. They cover:

- FastAPI health, query, schema, generation, and `/ask` behavior.
- Configuration and database relationships/constraints.
- Deterministic seed generation and expected volumes.
- Gemini provider behavior with a mocked SDK client; no Gemini network call is required for tests.
- AST security: allowed queries, CTEs, joins, aggregates, DML/DDL rejection, system tables, dangerous functions, unknown identifiers, complexity, limits, prompt injection, and repair security.
- Result intelligence: KPI formats, line/bar/pie/table selection, visualization validation, formatting, empty results, warnings, grounded summaries, and summary failure fallback.
- PostgreSQL read-only permissions via a marked integration test when a PostgreSQL analytics URL is configured.
- Production settings/secrets, CORS middleware configuration, request/body/context limits, rate limiting, health/readiness, error sanitization, pool/outage/timeouts, and metrics.
- Gemini timeout/rate-limit/5xx/model-unavailable/malformed responses and bounded retry configuration.
- Six-query SQLite-backed analytics smoke coverage with SQL execution and total API latency recorded as test properties.

Frontend tests live in `frontend/lib/api.test.ts` and `frontend/components/analytics/analytics-dashboard.test.tsx`; they cover API failure codes, network/timeout/malformed responses, invalid visualization metadata, empty results, conversation failures, retries, and duplicate submissions. Frontend checks are `npm test`, `npm run lint`, and `npm run build` from `frontend/`.

Run the standard checks from the repository root:

```bash
make test
make lint
```

An earlier Sprint 9 run reported `98 passed, 1 skipped`; the skip is the PostgreSQL-only permission test without its integration configuration. It is superseded by the latest full rerun above. Backend Ruff passed. Tests use mocked providers and do not require Gemini credentials.
Latest rerun, superseding the earlier 98-pass run below: backend `99 passed, 1 skipped` (PostgreSQL permission integration not configured); frontend `11 passed`, with lint and production build passing.

## 15. Completed Sprint Summary

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
- **Verification:** frontend tests and lint pass; Next.js production build and frontend Docker image build pass; full Compose stack started and `/api/v1/analytics/ask` smoke-tested through the frontend proxy. The current local demo uses a transient `LLM_MODE=mock` override; `.env` was not changed.
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

Implemented from `sprints.md` (S11-01 to S11-22); nothing was executed when it was written, so run `make test`, `make lint`, the frontend suite, and the PostgreSQL integration tests first.

- **Surface:** `frontend/next.config.ts` proxies an explicit route list only; `/query` and `/validate` are unmounted in production unless `ENABLE_DIRECT_SQL_ENDPOINTS`; `/metrics` needs `METRICS_TOKEN`; Compose publishes no backend port (`docker-compose.dev.yml` does, locally); Next.js sends CSP/frame/HSTS headers.
- **Auth and limits:** `app/core/auth.py` (JWT / static / disabled; production requires JWT), `app/core/rate_limit.py` (per-principal route dependency, stricter LLM limit), owner-scoped conversations with user-only turns, TTL and caps.
- **Data protection:** migration `b7c2d41f8a10` creates the `analytics` schema of PII-free, tenant-filtered views (`analytics.row_visible()` reading `app.scope` / `app.customer_id`); the role has no `public` privileges; the executor runs `SET TRANSACTION READ ONLY` plus `SET LOCAL` timeouts and tenant settings and uses `exec_driver_sql`. Deviation from the sprint text: tenant scoping lives in the views, not in RLS policies, because the view owner bypasses RLS.
- **Validator:** function allowlist, schema-qualifier and PII-column rules, derived-table aliases, allowlist derived from metadata, outer `LIMIT` enforcement with truncation.
- **Errors and repair:** SQLSTATE classification, `repair_hint` separate from the public message, conversation context in repair, `QUERY_GENERATION_FAILED` (422), and an overall request deadline (`REQUEST_DEADLINE_SECONDS`).
- **Prompting:** full schema in every prompt, follow-up-aware retrieval, current date, enum values, system instruction, temperature 0, one shared repair prompt, assistant turns store SQL/tables, Gemini attempts reduced to 2, default model pinned to `gemini-2.5-flash` (verify it is available to your account).
- **Results:** structural KPI detection, column-name-only formatting, multi-series charts, additive-only pies, distinct colours, short titles, direction-aware summaries; frontend sign-in prompt, generation-failed panel, truncated marker.

## 16. Known Limitations

- **Conversation persistence is in-memory:** sessions are not durable across backend restarts and are not backed by user identity.
- **Frontend conversation history is client state:** no account-level saved history or reload persistence is implemented.
- **Rate limiting and metrics are process-local:** use a shared gateway/metrics backend before running multiple application replicas.
- **Gemini readiness checks configuration, not remote quota/availability:** provider outages are surfaced safely when requests execute.
- **PostgreSQL init passwords apply only to fresh clusters:** existing roles require explicit password rotation and URL updates.
- **Compose targets local development:** the backend is no longer published, but production still needs private networking, a trusted TLS gateway, and a secret manager (`JWT_SECRET` and keys are plain environment variables).
- **No identity provider:** the API validates signed tokens and scopes queries to the token's customer, but nothing issues tokens in production (`backend/scripts/issue_token.py` is a development helper).
- **No cost-based query planner:** query controls use AST heuristics, join/nesting limits, result limits, and timeouts; they do not estimate database cost.
- **AST validator is defense in depth:** SQLGlot validation is stronger than regex but cannot be the sole security mechanism.
- **Deterministic summaries are the default:** Gemini summary generation is an extension point, not active default behavior, to avoid an unnecessary extra provider call.
- **Gemini availability is external:** a valid key/model can still receive provider-side capacity errors such as 503; API errors are handled without executing SQL.
- **Schema retrieval is keyword-ordered:** the full schema is sent by default (11 tables); narrowed keyword retrieval remains for larger schemas. No embeddings or vector store exist.
- **No cloud deployment or external observability platform:** deployment is documented for Docker Compose; logs/metrics are local to the application process.

## 17. Future Improvements

Sprints 1–11 are implemented; Sprint 12 is planned in `sprints.md`. Remaining improvements:

- Integrate an identity provider that issues the expected token claims.
- Persist conversation history with per-user ownership, retention, and deletion controls.
- Use a shared rate limiter and metrics aggregation if deploying multiple backend instances.
- Add external log/metric collection and deployment-specific alerting.
- Evaluate query-cost controls, stricter schema/views, or embeddings only when supported by measured needs.
- Deploy behind a trusted TLS gateway with private database and metrics access.

## 18. How to Resume Development

```text
Current stopping point:
Sprints 1–10 are complete.

Next task:
No sprint is currently in progress. Only start new work when explicitly requested.

Do not redo Sprints 1–10.

First:
1. Read progress.md.
2. Inspect the current repository and Git state.
3. Verify the current backend/frontend tests and Docker health status.
4. Understand the existing UI, provider, retrieval, validation, execution, and result-intelligence boundaries.
5. Confirm the requested scope before making future improvements.
6. Preserve existing APIs and SQL security boundaries unless explicitly required.
7. Run relevant tests and the complete suite where practical.
8. Update progress.md after completing the sprint.
```

There is no active sprint handoff. Treat the repository as the source of truth and do not infer new scope from the optional future improvements list.

## 19. Instructions for Future AI Agents

- Read `progress.md` before modifying the project.
- Treat the repository and tests as the source of truth.
- Inspect existing code before implementing anything.
- Do not rewrite working architecture unnecessarily.
- Do not duplicate existing functionality.
- Never bypass SQLGlot validation or the read-only analytics service.
- Never allow LLM output to execute without the existing security pipeline.
- Never trust LLM confidence, table metadata, summaries, or visualization metadata as security controls.
- Never commit `.env`, API keys, passwords, tokens, or database credentials.
- Do not print secrets while debugging configuration.
- Maintain the `LLMProvider` abstraction and preserve deterministic mock mode.
- Keep Gemini/network calls optional in tests; use mocked clients.
- Preserve the separate `DATABASE_URL` and `ANALYTICS_DATABASE_URL` roles.
- Keep migrations as the schema authority; do not replace them with application startup `create_all()`.
- Keep result intelligence independent of frontend code.
- Add focused tests for new functionality and retain regression coverage.
- Do not mark a sprint complete unless its acceptance criteria are actually verified.
- Do not implement future sprint functionality early unless explicitly requested.
- Prefer small, maintainable changes over unnecessary rewrites.
- Update `progress.md` after completing a sprint.
- Do not commit changes unless explicitly instructed.

## 20. Important Development Decisions

- **Gemini plus provider abstraction:** Gemini is the current configured real provider, but the API depends on `LLMProvider` so provider changes do not affect routes or security.
- **Mock mode:** deterministic mock SQL keeps local development, CI, and demos independent of API availability.
- **Independent SQL validation:** the LLM is untrusted; SQLGlot, allowlists, limits, and PostgreSQL privileges enforce safety outside the model.
- **Separate database roles:** migrations/application code use the owner URL while generated SQL uses `analytics_readonly`.
- **Repair revalidation:** a repaired query follows exactly the same validator and executor path; security errors are never automatically repaired.
- **Deterministic schema retrieval:** keyword retrieval is predictable and easy to test; embeddings are deferred until they solve a demonstrated need.
- **Deterministic visualization:** result shape is sufficient for initial chart selection, avoiding an unnecessary Gemini call and keeping chart metadata testable.
- **Summary isolation:** summaries run after execution and receive result data only; they cannot influence SQL generation or query execution.
- **Frontend separation:** the backend owns data interpretation and visualization contracts; the implemented frontend remains a consumer, not a security or analytics engine.
- **Migration-owned database:** Alembic provides reproducible schema creation and the seed marker prevents uncontrolled duplicates.

## 21. Current Git State

- **Branch:** `main`
- **Baseline for the stabilization pass:** `6ea3d59` (clean tree). Earlier milestones: Sprint 11 `abd5ac3`, Sprint 12 `23e1de5` (`e869768` is an identical-tree duplicate), merge `17dba09`, `440e7b9`.
- **Stabilization changes:** commit `fix: stabilize analytics copilot baseline` on top of `6ea3d59` (details in section 22).
- **Older reference points:** Sprint 9 `e1291e4`, Sprint 8 `5639dd7`, Sprint 7 `9554013`, Sprint 6 `d685fef`.

No secrets, API keys, passwords, or token values belong in this file.


## Sprint 12: reliability, quality gates, operations (implemented; core verified in section 22)

Written without running anything; the stabilization pass in section 22 later executed the backend, frontend, PostgreSQL/Redis integration and Docker Compose paths. Items that still need a real environment are listed there under "Not run".

- State: `ConversationStore` interface with in-memory and PostgreSQL implementations (`app/conversation/sql_store.py`, migration `c3d91e5a7b20`, operational tables on their own base); optional SQL cache; `python -m app.jobs.purge`.
- Safety: `EXPLAIN` cost pre-flight (`QUERY_COST_LIMIT`), `*_FILE` secrets with value-free startup errors, demo seed refuses production, validator now catches tokenizer/recursion errors.
- Observability: Prometheus metrics (`/api/v1/metrics/prometheus`), audit trail, readiness `degraded` semantics, operator diagnostics.
- Quality: PostgreSQL integration CI, golden evaluation suite (76 cases, `backend/evals`), validator fuzzing, coverage gates, mypy, supply-chain scans, Playwright+axe e2e, API contract test.
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

- Playwright + axe end-to-end tests (`make e2e`), the k6 load test, Trivy image scans, `pip-audit`, `npm audit`, and the long fuzz run: not run in this pass.
- Lockfile (`make lock` / `lock-check`): no `backend/requirements.lock` exists; the CI step only warns.
- JWT authentication and tenant isolation were verified by unit and integration tests only, not by a live JWT request against the Compose stack (the Compose run used `AUTH_MODE=disabled`, which production rejects). **Closed afterwards:** a live JWT run on an isolated Compose stack passed 19 of 19 tenant-isolation checks (see `docs/Sequence.md` section 19).
- Gemini was verified with two live calls only; it is not part of the deterministic suite. External failures (quota, latency, model changes) are not reproducible tests.
- Backup/restore drill, rollback rehearsal, release workflow, Kubernetes and ops assets: not exercised.
- Earlier slowness seen with Gemini (`REQUEST_DEADLINE_EXCEEDED`) matches defect 1 (valid SQL rejected, so a repair call consumed the 25 s budget). That causal link is inferred from the logs and from the two successful calls above; the original failing question was not replayed.

### How to start the verified application

```bash
# .env is required (copy .env.example and set both database passwords; LLM_MODE=mock needs no key)
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

With `LLM_MODE=mock`, the mock provider answers five questions deterministically: "What is the total number of active vehicles?", "What were the top 10 customers by revenue?", "Show monthly revenue for the last 12 months.", "Which vehicles had the highest idle time?", "Show fuel consumption by vehicle.". Ask them in the dashboard, or `POST /api/v1/analytics/ask` with `{"question": "..."}`.

### Simplification since this checkpoint

Dead code, the OpenAI provider, the SQL cache, OpenTelemetry tracing, the Redis rate limiter, the Kubernetes/release pipeline, and the `static` auth mode have been removed, and `ask` / `execute` were split into smaller methods. The decisions behind each, and the items deliberately kept (metrics duplication, audit and feedback, direct SQL endpoints, evaluation/load/e2e tooling), are in `docs/Sequence.md` sections 18 and 19, and `docs/README.md` indexes the documentation. The section 22 results above describe the state before those changes; the closing verification is in Sequence.md section 19.

### Files to study next

`backend/app/services/generation.py` (orchestration and repair loop), `backend/app/analytics/validator.py`, `backend/app/analytics/service.py`, `backend/app/llm/prompt.py`, `backend/app/db/analytics_surface.py` with migration `b7c2d41f8a10`, `backend/app/core/auth.py`, `backend/app/core/rate_limit.py`, `backend/app/main.py`, `frontend/next.config.ts`, `frontend/components/analytics/analytics-dashboard.tsx`, and `docs/Sequence.md`.

### Checkpoint commit

Verified state: the commit titled `fix: stabilize analytics copilot baseline`, directly on top of `6ea3d59`. The results above were obtained on this change set as a working tree before it was committed.
