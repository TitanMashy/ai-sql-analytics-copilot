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
| `OLLAMA_BASE_URL` | `http://localhost:11434` (`http://host.docker.internal:11434` in Compose) | Where Ollama listens. |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-request timeout sent to the provider. |
| `LLM_MAX_RETRIES` | `1` | Extra attempts after a transient failure. `0` to `3`. |
| `REQUEST_DEADLINE_SECONDS` | `25` | The whole question (generation, repairs and query) must finish inside this. |

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

The application side is implemented: `LLM_PROVIDER=ollama`, `LLM_MODEL=<a model you pulled>`, and
`OLLAMA_BASE_URL`. The application never pulls a model and never starts Ollama.

- Backend running directly on the same machine: `OLLAMA_BASE_URL=http://localhost:11434`.
- Backend in Docker Compose, Ollama on the host: leave `OLLAMA_BASE_URL` unset. Compose uses
  `http://host.docker.internal:11434` and maps that name for Linux too.
- A stopped Ollama fails in about a second with `LLM_PROVIDER_UNAVAILABLE`; a model that was not
  pulled gives `LLM_MODEL_UNAVAILABLE`.
- Do not expose Ollama beyond the machine that runs the backend.

**Verification status.** The code path is covered by wire-level tests that run the real Ollama
client against a local fake server (reply parsing, malformed output, missing model, server down).
Inference with a real model has **not** been verified in this environment. Run
`RUN_LIVE_LLM_TESTS=1 LLM_MODEL=<model> python -m pytest tests/test_llm_live.py -m live -k ollama`
on a machine with Ollama to check it. Setup steps for macOS, a starter model, and the Docker
networking walkthrough are written up with that verification.

## Tracing: do not enable LangSmith yet

`langsmith` is installed as a dependency of LangChain, and LangChain starts sending traces on its
own when `LANGSMITH_TRACING=true` (or the older `LANGCHAIN_TRACING_V2`) and a LangSmith key are in
the environment. A raw trace includes the prompt: the schema, the user's question and the
conversation context. **Do not set any `LANGSMITH_*` or `LANGCHAIN_*` variable for this
application.** Nothing in the code enables tracing, and the application does not yet sanitize
traces; that is added, off by default, in the next planned step.

## Tests

The default suite never calls an external service (it passes with outbound network blocked). Tests
that do are marked `live`, skipped unless `RUN_LIVE_LLM_TESTS=1`, and skipped with their reason when
a key or a running Ollama is missing; a skipped test is not a pass.
