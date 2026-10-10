# Model providers

How the application talks to a language model, how to choose one, and what happens when it fails.
The model is **untrusted**: whatever it returns goes through the same SQLGlot validation and
read-only, tenant-scoped execution as any other SQL, whichever provider produced it. Choosing a
provider changes who writes the SQL, never what is allowed to run.

## Choosing a provider

Selection is explicit and has no fallback.

| `LLM_PROVIDER` | Needs | Use for |
|---|---|---|
| `mock` (default) | nothing | tests, CI, demos. Deterministic and offline. Refused when `APP_ENV=production`. |
| `gemini` | `GEMINI_API_KEY` | Google Gemini over the internet. |
| `ollama` | `LLM_MODEL`, a running Ollama | a local model; no cloud key and no data leaves the machine. |

**There is no automatic fallback.** If the selected provider is down, the request fails with a
clear error. It is never silently sent to another provider, because a switch from a local model to
a cloud one would send data somewhere the operator did not choose.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock`, `gemini` or `ollama`. |
| `LLM_MODEL` | Gemini: `gemini-3.6-flash`; Ollama: none | Model id. **Required for Ollama.** Model ids are retired by providers over time, so set it explicitly. |
| `GEMINI_API_KEY` | none | Required for `gemini`. Also accepted as `GEMINI_API_KEY_FILE`. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` (`http://host.docker.internal:11434` in Compose) | Where Ollama listens. |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-request timeout sent to the provider. |
| `LLM_MAX_RETRIES` | `1` | Extra attempts after a transient failure. `0` to `3`. |
| `REQUEST_DEADLINE_SECONDS` | `25` | The whole question (generation, repairs and query) must finish inside this. |
| `LANGSMITH_TRACING` | `false` | Optional tracing. See [Tracing](#tracing-langsmith-optional-off-by-default). |

`LLM_MODE` and `GEMINI_MODEL` were replaced by `LLM_PROVIDER` and `LLM_MODEL`. If either is still
set the backend **refuses to start** and says which to rename, rather than ignoring it and quietly
running the mock provider.

## Errors

Every failure is mapped to a stable code. Provider text is used only to classify and is never copied
into a response or a log.

| Code | HTTP | Meaning | Retried? |
|---|---|---|---|
| `LLM_CONFIGURATION_ERROR` | 503 | Missing key or unusable provider settings | no |
| `LLM_CREDENTIALS_INVALID` | 503 | The provider rejected the credentials (for Gemini, HTTP 400 "API key not valid" counts) | no |
| `LLM_MODEL_UNAVAILABLE` | 503 | Unknown or retired model; for Ollama, a model that was not pulled | no |
| `LLM_RATE_LIMITED` | 503 | Quota or rate limit | no |
| `LLM_TIMEOUT` | 504 | The provider exceeded `LLM_TIMEOUT_SECONDS` | no |
| `LLM_PROVIDER_UNAVAILABLE` | 503 | 5xx, refused connection, or Ollama not running. After retries the message says so | **yes** |
| `LLM_PROVIDER_ERROR` | 502 | Anything else the provider raised | no |
| `INVALID_LLM_RESPONSE` | 502 | Empty or malformed output; never guessed into SQL | no |

SQL validation and security failures are not provider errors and are never retried as such. A
repairable validation failure is sent back for a bounded repair (`MAX_REPAIR_RETRIES`); a security
rejection is never repaired. Every repaired statement is validated again.

## Retries: one policy

The only transient-failure retry is the one in `LangChainSQLProvider`: `1 + LLM_MAX_RETRIES`
attempts, only for `LLM_PROVIDER_UNAVAILABLE`, with a short backoff, and not beyond half the
request deadline. LangChain's and the Google client's own retries are switched off (LangChain
defaults to 6), and a test counts the HTTP requests the real client makes to prove it. Retries
therefore cannot multiply with the repair loop or outlast the deadline.

## Gemini

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=...        # never commit; or GEMINI_API_KEY_FILE=/run/secrets/gemini_api_key
LLM_MODEL=gemini-3.6-flash   # set explicitly; ids retire
```

- `LLM_MODEL_UNAVAILABLE` for a model that used to work means Google retired it ("no longer
  available to new users"). Pick a current id; the model list your key can use is available from
  Google's models API.
- `503 ... high demand` is capacity on Google's side. It is reported as
  `LLM_PROVIDER_UNAVAILABLE` after the bounded retry.
- Gemini 3 models use fixed sampling and **ignore `temperature`**, so answers can differ between
  runs. Only `mock` is deterministic. Compare models by running the evaluation more than once.

## Ollama (local)

Ollama runs a model on your own machine. The application never pulls a model, never starts Ollama,
and never contacts a cloud provider when `LLM_PROVIDER=ollama`.

### Set up on macOS

1. **Install and start Ollama.** Either download the app from <https://ollama.com/download> or
   `brew install ollama`, then start it (the app starts the server for you; with Homebrew run
   `ollama serve` in a terminal). It listens on `127.0.0.1:11434` only, which is what you want.
2. **Pull one starter model.** This is a download of several GB and is always a manual step:

   ```bash
   ollama pull qwen2.5-coder:7b      # 4.7 GB (the Ollama library lists 4.7 GB for this tag)
   ```

   `qwen2.5-coder:7b` is a code-tuned model that is a reasonable first try for SQL. It is a
   *starting suggestion, not a measured recommendation*: it has not been evaluated against this
   dataset. Alternatives: `llama3.1:8b` (4.9 GB) or, with more memory, `qwen2.5-coder:14b`
   (9.0 GB). As a rough rule, plan for the model's download size plus a few GB of free memory. Pick
   by running the evaluation (below), and change the model with `LLM_MODEL` alone.
3. **Check Ollama itself:** `ollama list` shows the model, `curl http://127.0.0.1:11434/api/tags`
   answers.
4. **Configure and smoke test the backend** (from `backend/`, with the virtual environment active):

   ```bash
   export LLM_PROVIDER=ollama LLM_MODEL=qwen2.5-coder:7b
   python scripts/llm_smoke.py
   ```

   It checks, in order: the provider builds, the model answers and the reply parses, the SQL passes
   validation, and, if `ANALYTICS_DATABASE_URL` is PostgreSQL (the Compose database, migrated and
   seeded), the SQL runs through the read-only executor. It prints one `ok`/`FAIL` line per step and
   exits 0 only if every step that ran passed. Add `--question "..."` to try another question.
5. **Start the app.** Directly: `LLM_PROVIDER=ollama LLM_MODEL=... make dev`. In Docker Compose, put
   `LLM_PROVIDER=ollama` and `LLM_MODEL=...` in `.env` and run `docker compose up --build -d`.

### Backend in Docker, Ollama on the Mac

Inside a container, `localhost` is the container, not your Mac. Compose therefore defaults
`OLLAMA_BASE_URL` to `http://host.docker.internal:11434`, which Docker Desktop resolves to the host,
and maps that name on Linux as well. **Leave `OLLAMA_BASE_URL` unset in `.env`** unless you run
Ollama somewhere else.

- Ollama's default loopback binding (`127.0.0.1`) is enough on Docker Desktop. Do **not** set
  `OLLAMA_HOST=0.0.0.0` to "make it work": that exposes the model server to your whole network.
- Check from inside the container:
  `docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').status)"`
  prints `200` when the path works.
- On Linux (not Docker Desktop) a loopback-only Ollama is not reachable from containers; either run
  the backend outside Docker, or bind Ollama to the Docker bridge address only, never to all
  interfaces.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `LLM_PROVIDER_UNAVAILABLE` in about a second | Nothing is listening at `OLLAMA_BASE_URL`. Start Ollama; from Docker, check the address above. |
| `LLM_MODEL_UNAVAILABLE` | The model in `LLM_MODEL` is not pulled. `ollama list`, then `ollama pull <name>`. The app will not pull it. |
| `LLM_TIMEOUT` | The first request loads the model into memory and can be slow; later ones are faster. Raise `LLM_TIMEOUT_SECONDS` (and `REQUEST_DEADLINE_SECONDS` to match, below the frontend's 30 s), or use a smaller model. |
| `INVALID_LLM_RESPONSE` | The model did not return the JSON object the prompt asks for. Smaller models do this more often; try a larger or code-tuned model. It is a measured failure, never turned into SQL. |
| Container exits at start: `LLM_MODEL is required` | Ollama has no default model; set `LLM_MODEL`. |
| Readiness is `ready` but questions fail | Readiness never calls the provider, so an unreachable Ollama does not show there. Run `scripts/llm_smoke.py`. |

### What has and has not been verified

Verified in development: the real `ChatOllama` client against a stand-in server (parsing, malformed
output, missing model, server down); a container reaching a loopback-bound stand-in through
`host.docker.internal` and answering a question end to end; and `scripts/llm_smoke.py` against the
stand-in. **Not verified here: inference with a real model.** To check it on a machine with Ollama:

```bash
RUN_LIVE_LLM_TESTS=1 LLM_MODEL=qwen2.5-coder:7b python -m pytest \
    tests/test_llm_live.py -m live -k ollama -v
python -m evals.run_eval --provider ollama --model qwen2.5-coder:7b --subset all
```

## Tracing (LangSmith): optional, off by default

LangSmith can record the shape of each request for diagnosing latency, provider errors, malformed
output, validation failures and repair frequency. It is **off** unless `LANGSMITH_TRACING=true` and a
key are set, and it is never needed for the application, tests, or evaluation.

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...        # a secret; or LANGSMITH_API_KEY_FILE
LANGSMITH_PROJECT=analytics-copilot
# LANGSMITH_ENDPOINT=...     # only for a self-hosted or regional LangSmith
```

### What is sent, and what is not

Each operation becomes a small tree of runs named `analytics.ask` / `analytics.generate`,
`context_retrieval`, `prompt_construction`, `model_invocation` (one per attempt),
`response_parsing`, `sql_validation`, `repair` and `sql_execution`. A run carries **only** these
fields, each a short single token or a number:

`request_id`, `operation`, `provider`, `model`, `outcome`, `error_code`, `attempt`, `max_attempts`,
`repair_count`, `repair_attempt`, `row_count`, `tables_count`, `validation_status`, `case_id` (an
evaluation case id), `duration_ms`.

Runs are created with **empty inputs**. These are never sent: the question, the prompt (schema,
business definitions, conversation history), the model's reply, the generated SQL, result rows,
summaries, user, tenant and customer identifiers, auth tokens, API keys, and exception messages (a
failure is recorded as a code such as `LLM_PROVIDER_UNAVAILABLE`, because database errors can contain
SQL and parameters). Anything not on the list above, or not a short single token (letters, digits
and `_ . : - /` only), is
dropped before it leaves the process. The LangSmith client is also configured to hide inputs,
outputs and metadata as a second layer, and LangChain's own automatic tracing, which would record the
whole prompt, is switched off around every model call whatever the environment says.

The API key travels in the request header, not in the payload. The data flow is: backend process ->
(HTTPS) -> LangSmith (`api.smith.langchain.com`, or `LANGSMITH_ENDPOINT`). Treat the metadata above
as what you are agreeing to share.

### It cannot break a request

- Spans go onto a bounded in-process queue with a non-blocking put; a background thread exports them
  with short timeouts, no retries, and a circuit breaker. If LangSmith is slow or down, traces are
  dropped, not waited for.
- No tracing error can reach the request: tracing code is wrapped, and exceptions from the traced
  code pass through unchanged.
- Shutdown waits about a second for the queue. (LangSmith's own batching client was measured taking
  45 seconds to exit against an unreachable endpoint, which is why it is not used.)
- Enabled with no key, tracing is simply off and a warning is logged.

### Evaluation traces

During `python -m evals.run_eval`, each run is tagged with its golden-case id (`case_id`), so a
LangSmith project can be filtered by case. The local report is produced the same way with or without
LangSmith. No LangSmith datasets or experiments are created automatically.

## Tests

The default suite never calls an external service (it passes with outbound network blocked). Tests
that do are marked `live`, skipped unless `RUN_LIVE_LLM_TESTS=1`, and skipped with their reason when
a key or a running Ollama is missing; a skipped test is not a pass.
