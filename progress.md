# AI SQL Analytics Copilot: Project Handoff

This document is the persistent context for future coding agents. Read it before changing the repository. The repository and its tests are the source of truth; this document is a handoff summary, not a replacement for inspecting the code.

## 1. Project Overview

**AI SQL Analytics Copilot** is a backend-first analytics product for fleet-management SaaS data. A user asks a natural-language business question, such as "What were the top customers by revenue?", and the system retrieves relevant schema context, generates read-only PostgreSQL SQL, validates it independently of the LLM, executes it against a restricted analytics database, and returns rows plus result intelligence suitable for a future dashboard.

The target users are fleet operators, business analysts, and product/revenue teams who need answers from operational, utilization, maintenance, fuel, and billing data without hand-writing SQL. The project exists to make that workflow explainable and safer than allowing an LLM to execute arbitrary database output.

The technically interesting parts are the modular LLM provider boundary, deterministic schema/business-context retrieval, AST-backed SQL security, a separate PostgreSQL read-only role, bounded SQL repair, and post-query KPI/visualization analysis. The frontend is intentionally not built yet.

## 2. Current Status

```text
Current status: Sprints 1–6 COMPLETE
Next sprint: Sprint 7
Project is NOT finished.
Frontend work has NOT been completed; frontend/ contains only a placeholder.
```

| Sprint | Status | Description |
|---|---|---|
| Sprint 1 | COMPLETE | Repository foundation, FastAPI startup, configuration, logging, SQLAlchemy sessions, PostgreSQL Compose setup, tests, and developer tooling. |
| Sprint 2 | COMPLETE | Fleet-management PostgreSQL schema, Alembic migration, realistic deterministic seed data, indexes, schema metadata, and read-only analytics role. |
| Sprint 3 | COMPLETE | Analytics query/validation API, read-only execution service, result normalization, schema APIs, limits, timeouts, request IDs, and structured errors/logging. |
| Sprint 4 | COMPLETE | Natural-language SQL generation, schema retrieval, business definitions, provider abstraction, mock provider, Gemini provider, `/generate`, `/ask`, response parsing, and bounded repair. |
| Sprint 5 | COMPLETE | SQLGlot AST validation, table/column allowlists, dangerous-function/system-table protection, complexity rules, normalized SQL, repair security, and security tests/docs. |
| Sprint 6 | COMPLETE | Result analyzer, KPI detection, deterministic visualization selection/validation, summaries, data-quality warnings, frontend-ready `/ask` responses, and visualization documentation. |
| Sprint 7 | NOT STARTED | Conversational analytics and context management. |
| Sprint 8 | NOT STARTED | Next.js analytics dashboard/frontend. |
| Sprint 9 | NOT STARTED | Production hardening, observability, performance, and deployment improvements. |
| Sprint 10 | NOT STARTED | Final polish, documentation, demo preparation, and recruiter-facing presentation. |

The Git history contains one feature commit per completed sprint: `3588083`, `71b655a`, `5c6de51`, `270e7dd`, `3d288f6`, `06169fa`, and `d685fef`.

## 3. Product Capabilities

Implemented capabilities:

- FastAPI modular monolith with health, schema, SQL, generation, and combined analytics endpoints.
- PostgreSQL fleet-management dataset with deterministic demo seed data.
- Schema-aware retrieval based on table/column/business terminology.
- Business metric definitions for revenue, active vehicles, completed trips, fuel cost, idle time, and payments.
- Gemini provider using the official `google-genai` SDK and structured JSON output.
- Deterministic mock provider for development and CI without an API key.
- Shared provider interface with legacy OpenAI provider compatibility still present in the codebase.
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

Not implemented: frontend, conversational memory, authentication/authorization, vector schema retrieval, tenant-level policy enforcement, and a cost-based query planner.

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
```

Responsibilities:

- **FastAPI/API layer:** validates request bodies, attaches request IDs, exposes OpenAPI routes, and maps internal errors to structured responses. It does not execute SQL directly.
- **SchemaRetriever:** selects relevant application tables and business definitions using deterministic keyword/column relevance. It is ready for a future embedding implementation but has no vector database.
- **LLMProvider:** abstracts SQL generation and repair. `GeminiProvider` is the configured real provider; `MockLLMProvider` supplies deterministic queries for tests and demos.
- **SQLGenerationService:** coordinates question, schema context, provider output, bounded repair, and the existing analytics execution service. Generated SQL is never treated as trusted.
- **SQLValidator:** parses and validates PostgreSQL SQL before execution.
- **AnalyticsQueryService:** uses `ANALYTICS_DATABASE_URL`, applies PostgreSQL statement timeout, executes normalized SQL, enforces result limits, classifies database errors, and normalizes rows.
- **Result intelligence services:** run only after successful execution and cannot influence SQL generation or execution.
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
- Real provider selection is controlled by `LLM_MODE`; the default/example mode is `mock`, while the current local `.env` has been configured for Gemini. Never copy the local key into documentation or commits.

### Frontend

No frontend application has been implemented. `frontend/` currently contains only `.gitkeep`. Sprint 8 is the planned frontend sprint.

### Infrastructure

- Docker Compose services: `postgres` and `backend`
- Backend Dockerfile installs the editable project with development dependencies and copies application/Alembic files.
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
| GET | `/api/v1/health` | Checks application database connectivity. |
| POST | `/api/v1/analytics/query` | Validates and executes direct read-only SQL. Request: `{ "sql": "..." }`. Response: columns, rows, row count, execution time. |
| POST | `/api/v1/analytics/validate` | Returns normalized SQL, errors, warnings, referenced tables, and complexity metadata without executing. |
| POST | `/api/v1/analytics/generate` | Converts `{ "question": "..." }` into structured SQL without execution. Returns question, SQL, explanation, tables, schema context, provider, and confidence. |
| POST | `/api/v1/analytics/ask` | Generates SQL, validates/executes it, and returns SQL results plus summary, KPI, visualization, and warnings. |
| GET | `/api/v1/schema` | Returns all non-secret schema metadata. |
| GET | `/api/v1/schema/tables` | Lists available analytics table names. |
| GET | `/api/v1/schema/tables/{table_name}` | Returns one table's columns and relationships. |
| GET | `/docs` | FastAPI interactive OpenAPI documentation. |

Structured error codes include validation, parse, security, permission, timeout, table-not-found, provider, invalid-request, and execution errors.

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
│   │   ├── core/            # settings and structured logging
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
│   ├── security.md
│   └── visualization.md
├── frontend/                # placeholder only; no UI yet
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
| `DATABASE_URL` | Runtime/app DB | Migration and owner connection, e.g. `postgresql+psycopg://app@postgres:5432/app`. |
| `ANALYTICS_DATABASE_URL` | Analytics execution | Restricted read-only connection, e.g. `postgresql+psycopg://analytics_readonly@postgres:5432/app`. |
| `GEMINI_API_KEY` | Only when `LLM_MODE=gemini` | Google Gemini credential; never print or commit it. |
| `GEMINI_MODEL` | No; default `gemini-flash-latest` | Gemini model name. |
| `LLM_MODE` | No; default `mock` | `mock` for deterministic tests/demos or `gemini` for real provider mode. |
| `LOG_LEVEL` | No; default `INFO` | Structured application log threshold. |
| `MAX_RESULT_ROWS` | No; default `1000` | Maximum rows fetched/returned by analytics execution. |
| `QUERY_TIMEOUT_SECONDS` | No; default `10` | PostgreSQL statement timeout. |
| `MAX_QUERY_JOINS` | No; default `5` | AST complexity threshold. |
| `MAX_QUERY_NESTING` | No; default `3` | AST nesting threshold. |
| `MAX_REPAIR_RETRIES` | No; default `3` | Maximum repair attempts for repairable query errors. |
| `ENABLE_RESULT_SUMMARY` | No; default `true` | Enables deterministic post-query summaries. |

The code also retains legacy `OPENAI_API_KEY` and `OPENAI_MODEL` settings/provider compatibility from earlier work, but the current documented/configured provider path is Gemini. Do not add those legacy secrets to new deployments unless deliberately reactivating that provider.

## 14. Testing

Tests live in `backend/tests` and use pytest. They cover:

- FastAPI health, query, schema, generation, and `/ask` behavior.
- Configuration and database relationships/constraints.
- Deterministic seed generation and expected volumes.
- Gemini provider behavior with a mocked SDK client; no Gemini network call is required for tests.
- AST security: allowed queries, CTEs, joins, aggregates, DML/DDL rejection, system tables, dangerous functions, unknown identifiers, complexity, limits, prompt injection, and repair security.
- Result intelligence: KPI formats, line/bar/pie/table selection, visualization validation, formatting, empty results, warnings, grounded summaries, and summary failure fallback.
- PostgreSQL read-only permissions via a marked integration test when a PostgreSQL analytics URL is configured.

Run the standard checks from the repository root:

```bash
make test
make lint
```

The last verified local run reported `70 passed, 1 skipped`; the skip was the PostgreSQL-only permission test outside the live Compose environment. `make verify-permissions` was verified against the running PostgreSQL container. Tests do not require Gemini credentials because provider tests are mocked and the default test path is deterministic.

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

## 16. Known Limitations

- **No frontend:** intentionally deferred to Sprint 8; frontend currently has no implementation.
- **No conversation memory:** Sprint 7 work; current `conversation_context` is only an optional request field passed into generation.
- **No authentication or tenant authorization:** required before production multi-tenant use; database row ownership is modeled but API authorization is not implemented.
- **No cost-based query planner:** query controls use AST heuristics, join/nesting limits, result limits, and timeouts; they do not estimate database cost.
- **AST validator is defense in depth:** SQLGlot validation is stronger than regex but cannot be the sole security mechanism.
- **Deterministic summaries are the default:** Gemini summary generation is an extension point, not active default behavior, to avoid an unnecessary extra provider call.
- **Gemini availability is external:** a valid key/model can still receive provider-side capacity errors such as 503; API errors are handled without executing SQL.
- **Schema retrieval is keyword-based:** no embeddings or vector store exist.
- **No production deployment/Kubernetes/observability platform:** Docker Compose is the current infrastructure.
- **Legacy OpenAI compatibility remains in code:** Gemini is the current configured path; do not remove or rewire providers without an explicit requirement.

## 17. Remaining Roadmap

These sprints are planned and **NOT IMPLEMENTED**.

### Sprint 7 — Conversational Analytics and Context Management

Add conversation/session state, follow-up questions, prior-result context, clarification handling, and safe context windows. Preserve the existing SQL validation and read-only execution boundaries.

### Sprint 8 — Next.js Analytics Dashboard / Frontend

Build the frontend that consumes `/ask`, schema, and generation APIs. Render backend-owned KPI, table, bar, line, area, and pie metadata without moving SQL/security decisions into the browser.

### Sprint 9 — Production Hardening, Observability, Performance, and Deployment

Harden authentication/tenant isolation, query-cost and connection behavior, metrics/tracing/log aggregation, reliability/retries, deployment configuration, secrets management, and production database operations.

### Sprint 10 — Final Polish and Demo Preparation

Complete end-to-end polish, user-facing documentation, sample/demo flows, screenshots or presentation materials, recruiter-facing README/project narrative, and final acceptance verification.

## 18. How to Resume Development

```text
Current stopping point:
Sprint 6 is complete.

Next task:
Implement Sprint 7: conversational analytics and context management.

Do not redo Sprints 1–6.

First:
1. Read progress.md.
2. Inspect the current repository and Git state.
3. Verify the Sprint 6 tests and Docker/health status.
4. Understand the existing provider, retrieval, validation, execution, and result-intelligence boundaries.
5. Implement only Sprint 7.
6. Preserve existing APIs and SQL security boundaries unless Sprint 7 explicitly requires a change.
7. Run relevant tests and the complete suite where practical.
8. Update progress.md after completing the sprint.
```

The next agent should begin by examining `backend/app/services/generation.py`, the request schemas, and the existing tests for the smallest context-management seam. Do not begin frontend work or rewrite the SQL/security layer.

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
- **Frontend separation:** the backend owns data interpretation and visualization contracts so the future frontend remains a consumer, not a security or analytics engine.
- **Migration-owned database:** Alembic provides reproducible schema creation and the seed marker prevents uncontrolled duplicates.

## 21. Current Git State

- **Branch:** `main`
- **HEAD:** `d685fef feat(analytics): add result intelligence and visualization engine`
- **Remote:** `origin/main` points to the same Sprint 6 commit.
- **Recent sprint commits:** `06169fa` Gemini provider, `3d288f6` AST security, `270e7dd` SQL generation, `5c6de51` analytics API, `71b655a` database, `3588083` foundation.
- **Working tree before this document:** clean.
- **Expected state after creating this document:** only the new root `progress.md` should be uncommitted. Do not commit it unless explicitly requested.

No secrets, API keys, passwords, or token values belong in this file.
