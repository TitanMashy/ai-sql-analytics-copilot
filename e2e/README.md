# End-to-end tests

Browser tests that drive the real dashboard against the Docker Compose stack in mock-provider mode.
They are a separate package so Playwright and axe never become dependencies of the frontend image
or its lockfile.

```bash
# from the repository root
cp .env.example .env            # set POSTGRES_PASSWORD and ANALYTICS_DATABASE_PASSWORD
docker compose up -d --build    # migrate runs first, then backend and frontend
docker compose --profile demo run --rm seed

cd e2e
npm install
npm run install:browsers
npm test
```

Set `E2E_BASE_URL` to test a stack on another host. Raise `RATE_LIMIT_LLM_REQUESTS` (for example to
200) in `.env` when you run the suite repeatedly: every browser tests shares one client address, and
the default is 20 LLM-backed requests per minute.

What is covered: asking, KPI/chart/table rendering, several answers kept in one thread, reload
restore, delete, feedback, CSV export, pagination, truncation, the 401/429/504/422 error states,
that routes such as `/api/v1/analytics/query` and `/api/v1/metrics` are not reachable through the
frontend, security headers, and automated axe accessibility scans (serious and critical findings
fail the run). Answers rely on the five questions the deterministic mock provider understands;
error and large-result cases are produced by intercepting the ask request.
