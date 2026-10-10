# Frontend: AI SQL Analytics Copilot dashboard

A [Next.js](https://nextjs.org) (App Router) and React dashboard for asking natural-language questions and viewing the answer: the generated SQL, a KPI or chart, the result table, and warnings. It is written in TypeScript with Recharts for charts.

The browser talks only to this app. A same-origin proxy (`next.config.ts`) forwards an **allowlist** of routes to the backend (ask, conversations, schema tables and health); the direct-SQL and metrics routes are never forwarded, and no backend secret is exposed to client code. The security headers (CSP, frame, HSTS in production builds) are also set there.

## Run it

The normal way is the repository's Docker Compose stack, from the repository root (see the top-level [README](../README.md)):

```bash
docker compose up --build -d     # dashboard on http://localhost:3000
```

To run only the frontend against a backend that is already running:

```bash
npm ci
INTERNAL_API_URL=http://localhost:8000 npm run dev
```

| Variable | Default | Purpose |
|---|---|---|
| `INTERNAL_API_URL` | `http://localhost:8000` | Where the proxy forwards API calls (the backend, server side only) |
| `NEXT_PUBLIC_API_URL` | empty (same origin) | Base URL the browser uses; leave empty to use the proxy |

## Checks

```bash
npm run lint     # ESLint
npm test         # Vitest (API client, payload validation, components, proxy configuration)
npm run build    # production build
```

`contracts/` holds the API response contracts the backend test suite checks against, so a backend change that breaks the dashboard fails a test.

## Behavior worth knowing

- Every API payload is validated at runtime before it is rendered; generated SQL and backend text are shown as text, never as HTML.
- Invalid chart metadata is dropped and a chart failure is isolated to the chart.
- Requests time out after 30 seconds (the backend deadline is shorter), duplicate submissions are prevented, and only retryable failures offer a retry.
- Which model provider answers (mock, Gemini or Ollama) is a backend setting; the dashboard does not choose or know it. See [docs/llm-providers.md](../docs/llm-providers.md).

`AGENTS.md` carries the Next.js agent rules written by `next dev`; keep it.
