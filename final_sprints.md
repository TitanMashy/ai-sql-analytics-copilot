# AI SQL Analytics Copilot — Final Implementation Sprints

> **Status: completed.** Sprints 13, 14 and 15 were executed in order against this contract. The evidence, the live checks that were not run, and the final state are in [progress.md](progress.md) sections 23 to 25. This file is kept as the record of the plan.

**Purpose:** This is the execution contract for the final three coding-agent sprints. The agent must read this document, the current `progress.md`, `README.md`, any existing `sprints.md`, relevant architecture/security/deployment/evaluation docs, and the repository before making changes. **The repository and executable evidence are the source of truth; handoff documents can be stale.**

**Final sequence:** Sprint 13 → Sprint 14 → Sprint 15 (project closeout). These are the final planned sprints; Sprint 15 must close the project rather than propose another roadmap.

## 0. Agent operating rules

### Before editing
1. Read this document completely, then inspect the current codebase and relevant docs.
2. Check the current branch, `git status`, recent commits, dependency manifests/lockfiles, environment settings, provider implementation, SQL generation/repair pipeline, tests, Docker Compose, and CI.
3. Run the current relevant test/check baseline before changing code. Record the exact `HEAD`, commands, outcomes, and limitations.
4. Reconcile conflicting handoff notes against code and executable evidence. Never claim a check passed unless it was actually run.
5. Preserve user changes. Do not reset, discard, overwrite, or reformat unrelated work. Do not commit unless explicitly instructed.
6. Complete each sprint's acceptance criteria and exit gate before starting the next. Do not implement all three as one undifferentiated change.

### Existing product and security boundary
The intended flow is:

`Next.js → FastAPI → schema/business context → model generation → structured response parsing → SQLGlot validation → read-only PostgreSQL execution → result intelligence → UI`

The repository may already contain authentication and per-principal limits, tenant-scoped PII-free analytics views, a separate read-only role, SQLGlot validation/allowlists, bounded repair, query/deadline limits, bounded conversation context, result analysis, and a dashboard. **Verify each in the actual code; do not assume it exists merely because a document says so.**

**The model is untrusted.** LangChain and LangSmith must never become security authorities. Initial and repaired SQL must use the same independent SQL validation and read-only execution path. Do not move tenant restrictions, permissions, SQL validation, or query limits into prompts, callbacks, or model wrappers.

### Scope discipline
- Keep the current modular monolith and make focused changes only.
- Use LangChain for model integration/orchestration, while the application owns product contracts, prompts, bounded repair, policy, validation, execution, and application error semantics.
- Support explicit provider selection. **Do not implement automatic cloud/local fallback**: it can silently route data to a cloud service and make evaluation hard to interpret.
- Do not add LangGraph, agentic tool loops, vector databases, embeddings, fine-tuning, queues, Redis/Kubernetes, new frontend features, or unrelated database/product features.
- Do not retain two competing orchestration layers. Avoid broad cleanup and opportunistic refactors.
- Fix adjacent defects only when they block an acceptance criterion or materially affect security, correctness, or reliability in the changed path.

### Definition of done for every sprint
A sprint is complete only when its acceptance criteria are verified, relevant tests/lint/type checks/builds pass, docs/config match actual behavior, and `progress.md` records evidence. Provider-dependent tests must not require external credentials in the default suite. Report blocked/unavailable checks with the exact reason; never silently mark them passed.

---

# Sprint 13 — LangChain Orchestration and Explicit Provider Switching

## Goal
Replace provider-specific model invocation/orchestration with one small LangChain-backed model layer, while preserving the current application-owned provider boundary and deterministic mock mode. Establish the common contract for Gemini and Ollama; complete Ollama onboarding and LangSmith instrumentation in Sprint 14.

## 13.1 Audit the current generation path
- Trace `/api/v1/analytics/generate` and `/api/v1/analytics/ask` through context retrieval, prompt construction, model invocation, response parsing, repair, validation, execution, and result intelligence.
- Identify the provider protocol, all call sites, structured-output handling, retry/timeout/deadline behavior, error mapping, and mock configuration.
- Identify duplicate retry loops before changing them. Do not rewrite routes or the entire generation service just to introduce LangChain.

**AC:** The sprint report identifies the actual path and changed modules; the change surface is bounded; existing API/UI contracts remain compatible unless a documented defect requires a correction.

## 13.2 Create one central, application-owned model boundary
Introduce or adapt a central model factory/configuration layer using current repository conventions. Do not create parallel abstractions. Use supported LangChain chat-model integrations for provider invocation and keep API routes/services independent of provider-specific classes.

The boundary should support the capabilities the app actually needs: invoke a configured chat model, produce/parse a structured SQL-generation response, apply finite timeout/deadline/retry behavior, translate provider errors into stable app-level categories, and expose safe provider/model metadata for logs/evaluation.

Responsibility split:
- **LangChain:** provider integration and model invocation mechanics.
- **Application model factory/settings:** explicit provider/model selection and validated configuration.
- **Existing app services:** schema/business retrieval, prompt policy, SQL response contract/parsing, bounded repair, stable errors.
- **Existing security/execution layer:** SQLGlot validation, allowlists, tenant restrictions, read-only DB access, row/time limits.
- **Existing result intelligence:** KPIs, summaries, visualization metadata.
- **LangSmith (Sprint 14):** optional tracing/evaluation only.

## 13.3 Provider modes and configuration
Support these modes through the same boundary:
- `mock`: deterministic, offline, test/CI/demo mode;
- `gemini`: existing Gemini cloud model via the appropriate LangChain integration;
- `ollama`: a valid configuration/factory slot for Sprint 14's local integration.

Use clear validated settings (for example `LLM_PROVIDER`, `LLM_MODEL`, credentials/provider settings, generation parameters, and timeout/retry limits), consistent with existing naming. Avoid duplicate settings for the same concern.

Requirements:
- Provider selection is explicit. Invalid configuration must fail clearly; never silently choose another provider.
- Gemini mode reports invalid credentials, rate limits, unavailability, timeout, malformed output, and exhausted retries clearly.
- Mock mode requires no cloud credentials and is deterministic across runs.
- No secrets in logs, API responses, traces, exception text, frontend bundles, or committed files.
- Do not change public API contracts solely for the migration.

## 13.4 Structured responses, repair, and bounded execution
- Use a supported structured-output feature where reliable; otherwise use one consistent application-owned parser and schema validation path.
- Malformed output is a classified generation failure, not something to guess into SQL.
- Preserve bounded, deadline-aware repair. Do not multiply retries across the application, LangChain, and provider SDK.
- Do not retry SQL validation/security failures as transient provider failures.
- Every repaired SQL statement must pass the same full validation and read-only execution path as the original.
- Preserve request IDs and value-safe structured logs.

## 13.5 Tests
Add/adjust tests for:
- factory selects configured provider; invalid provider/configuration fails clearly;
- mock generation is deterministic and offline;
- structured response parsing/schema validation;
- unavailable provider, timeout, rate limit, invalid credentials, malformed output, and retry exhaustion map to stable errors;
- `/generate` and `/ask` contracts remain stable;
- repair is bounded and revalidated;
- no provider path reaches SQL execution before validation;
- existing security/tenant-isolation tests remain passing.

Live Gemini tests must be opt-in. The default suite must not call external APIs.

## Sprint 13 acceptance checklist
- [ ] One central LangChain-backed model factory/boundary exists; routes do not construct provider SDK clients directly.
- [ ] `mock` and `gemini` use the same boundary.
- [ ] `ollama` configuration is prepared without claiming local inference has been verified yet.
- [ ] Structured parsing, errors, timeout, retry, and repair behavior are bounded and consistent.
- [ ] SQLGlot and read-only execution remain independent of LangChain.
- [ ] Tests cover selection, failures, parsing, repair bounds, and validation-before-execution.
- [ ] Relevant backend tests, lint/type checks, and frontend contract tests pass.
- [ ] Environment examples and provider setup docs reflect real behavior.
- [ ] `progress.md` records files changed, commands, outcomes, and limitations.

**Exit gate:** Do not start Sprint 14 until offline/mock tests pass and no unvalidated SQL execution path has been introduced.

---

# Sprint 14 — Ollama, Optional LangSmith, and Cross-Provider Evaluation

## Goal
Make local inference practical on the user's Mac, add privacy-conscious optional LangSmith tracing, and compare provider behavior using the project's existing evaluation assets. LangSmith is not an uptime dependency; Ollama does not guarantee Gemini-equivalent quality or latency.

## 14.1 Complete and verify Ollama
Use the supported LangChain Ollama integration unless a concrete repository constraint makes it unsuitable. Keep it behind the Sprint 13 factory.

Document a working setup to install/run Ollama on macOS, pull one starter model appropriate for structured SQL generation and available memory, configure `LLM_PROVIDER=ollama` and `LLM_MODEL`, start the backend, and run a repeatable smoke test. Record the exact model identifier and observed environment/results. Do not claim a model is “best” without evaluation; model changes should be configuration-only.

Networking and operations:
- If backend runs in Docker and Ollama runs natively on the Mac, container `localhost` is not the host. Document and verify a reachable endpoint such as `host.docker.internal` where supported.
- Do not expose Ollama publicly or bind it broadly without a necessary, documented reason.
- Ollama must not be a required Compose dependency for mock-mode development or CI.
- Do not download large models automatically during app startup or CI.
- A missing/stopped Ollama service must return a useful provider-unavailable error, not a fake success or indefinite hang.

**AC:** Local inference works without a cloud API key; `/generate` and `/ask` contracts are preserved; a local smoke test checks invocation, parsing, validation and, where configured, read-only execution; setup/network troubleshooting is documented; default tests do not require Ollama or a model download.

## 14.2 Add optional LangSmith tracing
Use the official LangSmith integration appropriate to the installed LangChain version. Trace meaningful stages only:
1. request/operation metadata;
2. schema/business context retrieval;
3. prompt construction;
4. model invocation;
5. structured response parsing;
6. SQL validation result;
7. repair attempt, if any;
8. execution outcome/final status.

Use allowlisted metadata such as request ID, provider/model, duration, outcome category, retry/repair count, and evaluation case ID. Keep traces useful for diagnosing latency, provider errors, malformed output, validation failures, and repair frequency without capturing raw business data.

Privacy and runtime requirements:
- Tracing is **off by default** (for example, `LANGSMITH_TRACING=false`).
- Credentials/project settings are environment configuration only; never commit them.
- By default, do not send raw user questions, generated SQL, result rows, conversation history, tenant/customer identifiers, auth tokens, credentials, or other sensitive payloads to LangSmith.
- Redact/minimize payloads before trace submission. Never log result rows just to improve traces.
- App startup, tests, validation, execution, and successful analytics requests must not depend on LangSmith availability.
- A LangSmith timeout/outage/configuration error must not turn a successful analytics request into a failure. Do not add queues/infrastructure solely for tracing.
- Do not suppress core application exceptions merely because tracing is enabled.

**AC:** Tracing is disabled by default; enabled traces contain useful sanitized metadata; automated tests prove startup/default tests do not require LangSmith and trace failures do not change core correctness; privacy behavior is documented. Live LangSmith checks are optional and reported as passed only if run.

## 14.3 Cross-provider evaluation
Reuse the existing golden evaluation dataset and harness. Do not replace it without a demonstrated gap. Existing handoff material refers to 76 total cases but also a much smaller mock-scored subset (previously five); inspect the current files and report exact totals and the number actually scored for each provider. Never report unscored cases as passing.

Evaluate as available:
- deterministic mock regression;
- Gemini with valid credentials/service availability;
- Ollama with the selected local model running.

Report separate measurements for:
- total cases vs scored cases;
- valid SQL / SQLGlot acceptance and security outcomes;
- semantic/business-answer correctness where expected results exist;
- parse failures, execution success, repair frequency, provider errors, latency, and relevant resource observations.

Use the same prompts, schema context, cases, and scoring rules for fair comparison. Record provider/model identifiers and settings. Keep live evaluations opt-in; ordinary CI remains deterministic. The local evaluation command/report must work without LangSmith. LangSmith can receive experiments/results when explicitly configured. Do not weaken expected answers or invent thresholds to make a provider pass; establish the baseline first and explain any chosen threshold.

## 14.4 Focused reliability fixes
Fix issues in the changed model path: actionable provider error categories; one finite retry/deadline policy; no nested retry multiplication; predictable config/readiness behavior; value-safe logs and existing metrics for provider/model, duration, outcome, retries and repair count where supported.

**No automatic fallback.** If Ollama is selected and unavailable, return a clear error. Do not silently send data to Gemini or another cloud provider. Provider selection must be reproducible and privacy-visible.

## Sprint 14 acceptance checklist
- [ ] Ollama is integrated through the central factory and works without cloud credentials.
- [ ] Ollama is optional for CI and mock-mode startup.
- [ ] Unavailable Ollama and invalid output produce clear errors.
- [ ] LangSmith tracing is opt-in, off by default, sanitized, and non-critical.
- [ ] Sensitive prompts, SQL, rows, conversations, tenant data and credentials are not traced by default.
- [ ] Local evaluation works without LangSmith; optional experiments work when configured.
- [ ] Provider comparison reports total/scored cases, SQL validity/security, semantic correctness, latency and errors honestly.
- [ ] All provider modes retain the same validation/execution security boundary.
- [ ] Mac setup and Docker-to-host networking are documented.
- [ ] Relevant backend/frontend/integration/lint/type/build checks pass; live checks are labeled accurately.
- [ ] `progress.md` records exact model, commands/results, tracing privacy behavior and limitations.

**Exit gate:** Do not start Sprint 15 until configuration can switch among mock/Gemini/Ollama, tracing cannot break core requests, and at least one honest evaluation report exists. If a live service is unavailable, complete deterministic checks and record the live run as blocked rather than fabricating results.

---

# Sprint 15 — Final Hardening, Documentation Reconciliation, and Closeout

## Goal
Close the project with a reproducible, demonstrable repository and evidence-based handoff. No new major features are permitted in this sprint. The output is a verified checkpoint, not another roadmap.

## 15.1 Run the full relevant verification suite
Discover and run the repository's canonical commands from Makefile/CI/docs. Cover as applicable:
- backend unit tests;
- PostgreSQL integration and read-only permission tests;
- backend lint/format/type checks;
- frontend tests, lint, type checks, production build;
- migration upgrade/downgrade/re-upgrade where supported;
- SQL validator regression/fuzz tests if present;
- auth, per-principal limits, tenant isolation, proxy allowlist, and no-PII analytics access tests;
- Docker Compose startup/health/readiness and a mock-mode end-to-end request through the frontend proxy;
- provider smoke tests for modes available in the current environment.

Use real repository commands; do not assume every item has a corresponding script. Do not add heavy tools/services just to lengthen the checklist. Mock-mode checks must be reproducible offline. Gemini, Ollama, and LangSmith live checks have their own prerequisites and must be labeled not run/blocked when unavailable, with the exact reason.

## 15.2 Verify security invariants
Prove through tests or explicit evidence that:
1. The model never executes SQL directly.
2. Initial and repaired SQL both pass SQLGlot validation.
3. Only approved analytics views/tables, columns, and functions are allowed.
4. The execution role is read-only and cannot access forbidden base tables or PII.
5. Tenant isolation remains enforced by the existing database/view and auth design.
6. Row, query-time and request-deadline limits remain enforced.
7. Provider choice cannot bypass validation or tenant policy.
8. Provider outage, LangSmith outage, malformed output and retry exhaustion produce classified errors—not unsafe execution or fabricated success.
9. Secrets/sensitive payloads are not exposed in API responses, logs, browser configuration, or default traces.
10. The frontend proxy exposes only intended routes; direct SQL/validation/metrics routes remain inaccessible through the UI origin if that is the intended current policy.
11. Mock mode is deterministic and usable without cloud/local services.

Fix defects that materially violate these invariants or block acceptance. Document serious unrelated findings instead of letting the sprint expand indefinitely.

## 15.3 End-to-end walkthrough
Run and record a concise manual/scripted mock-mode walkthrough:
1. Start the documented local stack and authenticate as required.
2. Submit a normal analytics question through the frontend.
3. Verify the expected UI/API contract, SQL handling, results, KPI/chart metadata and summary.
4. Test a follow-up question if conversational functionality is still part of the current product.
5. Trigger/simulate provider failure; verify a useful error and no fabricated result.
6. Verify forbidden SQL is rejected before execution.
7. Confirm health/readiness matches the documented deployment mode.

Where feasible, repeat the core request through Gemini and Ollama. Record which paths were actually exercised; do not imply unavailable live paths passed.

## 15.4 Reconcile documentation
Update at minimum, if present:
- `README.md`: actual stack, providers, quick start, environment variables, mock/Gemini/Ollama setup and test commands;
- `progress.md`: completed Sprints 13–15, final verification evidence, final Git checkpoint, limitations and unrun checks;
- architecture docs: model factory/LangChain role and unchanged SQL security boundary;
- deployment/operations docs: provider setup, timeouts/errors, health/readiness and optional tracing troubleshooting;
- evaluation docs: total dataset vs scored cases, local evaluation command, live provider comparison and metric interpretation;
- threat-model/security docs: external trace data flow, redaction defaults and no-auto-fallback policy;
- `.env.example` or equivalent: supported settings with safe defaults/placeholders;
- dependency/lock/CI/Docker docs where changed.

Remove stale provider claims, contradictory sprint statuses and obsolete setup instructions. Keep useful historical results but label them historical. Reconcile hashes/statuses with the actual final repository; do not trust stale commit references.

## 15.5 Repository hygiene and final checkpoint
- Inspect `git diff`, `git status`, dependencies/lockfiles, generated files, secrets, and accidental local artifacts.
- Ensure no keys/tokens, local DB dumps, private evaluation data, model weights, or machine-specific absolute paths are committed.
- Ensure lockfiles and installation instructions are consistent to the extent the environment allows.
- Keep network-dependent tests clearly marked as live integration tests.
- Do not broad-refactor, rewrite history, or commit unless explicitly instructed.
- Record final branch, exact `HEAD` hash, working-tree status, checks run, providers actually tested, evaluation results, security invariants verified, known limitations and commands for switching providers/running locally.

## Sprint 15 acceptance checklist
- [ ] All canonical automated checks possible in the environment have real recorded outcomes.
- [ ] Mock-mode end-to-end walkthrough passes.
- [ ] SQL security, tenant isolation, read-only permissions and provider-independent validation have regression evidence.
- [ ] Live provider/LangSmith checks are separated from deterministic checks and not falsely reported as passed.
- [ ] README, progress, architecture, evaluation, security and deployment docs agree with shipped code.
- [ ] Environment examples and dependency/lock files match the implementation.
- [ ] No secrets or generated model/database artifacts are present.
- [ ] Final branch, `HEAD`, and working-tree status are recorded accurately; user changes are preserved.
- [ ] `progress.md` contains a final closeout section and no sprint is marked complete without evidence.
- [ ] Final agent response gives a concise closeout report and proposes no additional sprint.

**Project closure gate:** The project is closed when mock-mode operation is reproducible, the independent SQL security boundary remains intact, provider switching is explicit, Ollama works when its runtime is available, LangSmith is optional and privacy-conscious, evaluation is honest, docs match the repository, and the final checkpoint is recorded. An external service outage does not block deterministic closure if the live check is clearly marked blocked/not run and all local criteria pass. A broken mock path, failed security invariant, or unvalidated SQL execution path blocks closure.

---

# Cross-sprint rules

## Security is invariant
- Never trust model-generated SQL.
- Never bypass SQLGlot validation, tenant restrictions, or read-only execution controls.
- Never silently switch from a local provider to a cloud provider.
- Never send sensitive payloads to LangSmith by default.
- Never expose credentials in logs, traces, responses, browser bundles, or committed config.
- Keep provider errors distinct from validation and execution errors.

## Reliability is bounded
- All timeouts/retries are finite and respect the request deadline.
- Avoid nested retry multiplication.
- Provider outages fail clearly and promptly.
- Mock mode remains deterministic and independent of external services.
- Optional observability is not a runtime dependency.

## Evaluation is evidence-based
- Report exact commands and observed results.
- Distinguish total dataset size from scored cases.
- Distinguish SQL validity from business-answer correctness.
- Record provider/model and latency/error observations.
- Never weaken expected results to manufacture a pass.

## Every change must be explainable
For each nontrivial change, the agent should be able to answer: Which acceptance criterion required it? What existing behavior does it preserve? Which test proves it works? Does it alter a security boundary, API, or config contract? Is there a simpler way to meet the criterion? If no criterion or material defect justifies it, do not include it.

# Final completion checklist

- [ ] Central LangChain-backed model factory/orchestration is implemented.
- [ ] `mock`, `gemini`, and `ollama` can be selected explicitly through configuration.
- [ ] Mock mode is deterministic and offline.
- [ ] Ollama Mac setup and Docker-to-host connectivity are documented and tested where available.
- [ ] LangSmith is opt-in, off by default, sanitized, and non-critical.
- [ ] Local evaluation works without LangSmith; provider comparisons are honest.
- [ ] All generated/repaired SQL uses the existing independent validation and read-only database controls.
- [ ] Relevant backend/frontend/integration checks have recorded outcomes.
- [ ] Documentation/configuration matches the implementation.
- [ ] Final Git checkpoint, limitations, and verification evidence are recorded.
- [ ] Sprint 15 closeout report is complete; no further sprint is proposed.
