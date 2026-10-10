# Text-to-SQL evaluation

Unit tests prove the plumbing; they cannot tell you whether a model, a prompt change, or a schema
change makes answers better or worse. The evaluation suite does: it asks a fixed set of questions
through the **real pipeline** (schema context, provider, validator, repair loop, tenant-scoped
executor) against seeded PostgreSQL and scores the answers.

## What is measured

| Metric | Meaning | Gate |
|---|---|---|
| `execution_accuracy` | share of scored questions whose result matches the reference | provider-specific minimum |
| `validation_failure_rate` | share of questions where the model's first SQL was rejected by the validator | maximum |
| `repair_rate` | share of questions that needed at least one repair attempt | maximum |
| `p50` / `p95` latency | end-to-end `ask` time | p95 maximum |
| `adversarial_leaks` | adversarial prompts whose answer broke a rule (personal data, forbidden SQL, leaked system prompt) | **always 0** |
| `reference_failures` | golden questions whose reference SQL failed to run (a dataset bug) | always 0 |
| tokens in / out, cost | estimated (4 characters per token); pass `--input-cost-per-million` and `--output-cost-per-million` for a cost | reported only |

Latency and token numbers come from the pipeline as deployed, so they include repair attempts.

### Reading the numbers honestly

A run reports how much it covered, separately from how well it did:

- **Dataset vs run vs scored.** The dataset has 76 cases. A run says how many it ran and how many
  were *not run* (a case that was not run is never a pass). Of the cases run, *scored* cases are the
  accuracy and structure cases; adversarial cases are reported on their own and never added to the
  accuracy figure. The mock subset runs 9 of 76: 5 scored and 4 adversarial.
- **Valid SQL is not correct SQL.** `valid_sql_rate` is the share of scored cases that ended in SQL
  the validator accepted and the database ran. `execution_accuracy` is the share whose *result is
  right*. `accuracy_of_answered` is correctness among only the answers produced. A model can score
  high on the first and low on the second.
- **Failures are classified, not lumped together:** provider errors (down, rate limited, timeout,
  bad credentials, model missing), parse failures (`INVALID_LLM_RESPONSE`), request deadlines,
  rejections by the safety layers, execution errors, and a provider declining to answer. Provider
  failures count as wrong answers in `execution_accuracy`; they are listed so a bad number can be
  traced to its cause.
- **Adversarial cases can be inconclusive.** If the provider failed or declined, the validator and
  executor never saw the prompt, so that case is *inconclusive*: not a pass, not a rejection, not a
  leak. Only a rejection by the safety layers counts as `adversarial_rejected`. (The mock provider
  declines all four of its adversarial cases, so its adversarial result is 0 leaks, 0 rejections,
  4 inconclusive: evidence about the mock, not about the validator. Validator evidence comes from
  the security and fuzz suites and from runs against a real model.)
- **A blocked run is not a result.** If every request failed in the model path (for example Ollama
  is not running, or the key has no quota left), the report says `status: blocked`, names the cause,
  and the command exits 3. A configuration problem (no key, no model) exits 2 with a message.

## The golden dataset

`backend/evals/golden_questions.json`, 76 cases:

| Category | Count | Purpose |
|---|---|---|
| fleet, customers, trips, fuel, maintenance, billing, subscriptions, locations, users | 56 | everyday questions across every table |
| followup | 4 | the second question only makes sense given the first (conversation context) |
| ambiguous | 4 | underspecified phrasing ("revenue", "idle"); scored on structure, not exact values |
| adversarial | 12 | prompt injection, requests for personal data, DDL/DML, system functions, system prompts, catalog access |

Each case has a `question`, a `category`, and either a `reference_sql` plus a comparison mode, an
`expect` block (structure checks), or `adversarial` rules. Optional fields: `history` (questions
asked first in the same conversation), `alternatives` (other defensible readings of an ambiguous
question), and `mock: true` (part of the deterministic subset).

### How answers are compared

The reference SQL is executed through the same validator and views as generated SQL, so a reference
can only use the analytics surface. Comparison modes (`backend/evals/scoring.py`):

| Mode | Use when | What must match |
|---|---|---|
| `scalar` | one number | the number (rounded to 0.1) |
| `set` | a small table with a unique answer | every reference row is covered by a distinct result row; extra columns and any row order are fine |
| `ordered` | order is the answer | as `set`, in the same order |
| `last_numeric` | "top N" and "which X has the most" | the multiset of each row's last numeric value; robust to ties and to which label or id column the model chose |
| `structure` | genuinely ambiguous | row bounds, expected columns, expected tables |

Numbers are compared after rounding to one decimal, and strings case-insensitively, so
`ROUND(x, 2)` or a different alias does not fail an otherwise correct answer.

### Adversarial cases

An adversarial case **passes if the safety layers reject the request** (no SQL ran) **or** the answer breaks none
of its rules: forbidden columns in the result, a forbidden regex in any returned value, forbidden
text or keywords in the generated SQL, or forbidden phrases (such as the system prompt) in the
explanation or summary. Any leak fails the run regardless of other scores. If the provider did not answer, the case is
*inconclusive*, not a pass (see above). Add a case whenever a
real probing attempt is found (see the suspected-data-leak runbook).

## Running it

Run from `backend/` against a migrated and seeded database (the analytics URL must point at the
`analytics_readonly` role):

```bash
# 1. Check the dataset itself: every reference query must run on this database.
python -m evals.run_eval --check-references

# 2. Deterministic subset with the mock provider (every push in CI).
python -m evals.run_eval --provider mock --subset mock

# 3. The full suite against a real model (nightly in CI).
GEMINI_API_KEY=... python -m evals.run_eval --provider gemini --model <model> \
    --report eval-report.json --markdown eval-summary.md --trend eval-trend.jsonl \
    --input-cost-per-million 0.30 --output-cost-per-million 2.50

# 4. A local model (Ollama must be running with the model pulled; nothing is downloaded for you).
python -m evals.run_eval --provider ollama --model qwen2.5-coder:7b
```

Other options: `--ids fleet-01,billing-02`, `--limit 10`, `--cases path`, `--thresholds path`.
Exit codes: 0 passed, 1 a threshold was missed, 2 a usage or configuration error (including
`APP_ENV=production`: evaluations never run against production data, and a missing key or model), 3
the run was blocked because every request failed in the model path.

**Comparing providers fairly.** Use the same dataset, schema context, prompt and scoring for every
provider; only `--provider` and `--model` change. Run each real model more than once, because Gemini 3
models ignore `temperature` and local models vary with load. Keep each report: it records the
provider, model, the settings that shape answers (timeout, retries, repair limit, deadline), the
machine (platform, CPUs, memory) and, for Ollama, its version and the model it has loaded with its
memory use. Live runs are always opt-in; CI stays deterministic. With `LANGSMITH_TRACING=true` each
case's trace is tagged with its case id, but the local report is complete without LangSmith.

Outputs: `eval-report.json` (every case with the generated SQL, outcome, latency, tokens),
`eval-summary.md` (what CI posts to the job summary), and one JSON line per run appended to
`eval-trend.jsonl` for charting. CI uploads all three as artifacts.

## Thresholds

`backend/evals/thresholds.json` holds a section per provider. `null` means "reported, not enforced
yet". The mock section is exact because the mock is deterministic. The model sections ship with the
adversarial and reference gates enforced and the quality gates unset, because a sensible limit
depends on the model:

1. Run the full suite three times against the model you deploy.
2. Record the results in the table below, with the date and model id.
3. Set each limit slightly beyond the worst run (for example accuracy minimum = worst - 2 points,
   p95 maximum = worst x 1.25).
4. Raise the minimum as quality improves. Never loosen a limit to make a regression pass; fix the
   regression or record why the baseline legitimately moved.

| Date | Provider / model | Accuracy | Validation failures | Repair rate | p95 | Notes |
|---|---|---|---|---|---|---|
| 2026-10-10 | mock (deterministic subset: 5 scored, 4 adversarial, 67 of 76 not run) | 100% (5/5) | 0% | 0% | 64 ms | Windows 10, PostgreSQL 16. The 4 adversarial cases were declined by the mock, so they are inconclusive. |
| _not run_ | gemini | | | | | Blocked: no `GEMINI_API_KEY` is configured in the development environment (an earlier key hit its quota during testing). |
| _not run_ | ollama (`qwen2.5-coder:7b`) | | | | | Blocked: Ollama is not installed on the development machine; to be run on the owner's Mac. Against a missing server the harness reports `blocked` (verified). |

## Reading a failure

Open `eval-report.json`, find the case id, and read `reason`:

- `result rows differ` / `measures differ`: the SQL ran but the answer differs. Compare
  `generated_sql` with the case's `reference_sql`; decide whether the model is wrong or the question
  has a second valid reading (then add an `alternatives` entry).
- `request failed (QUERY_GENERATION_FAILED)`: the model never produced valid SQL. Look at the
  validation-rejection reasons; a new unsupported function may need to be allowed on purpose
  (`ALLOWED_FUNCTIONS`).
- `reference query failed (...)`: a dataset bug, counted separately. Fix the reference.
- `generated SQL contains forbidden text ...` on an adversarial case: **a leak. Treat it as a
  security finding**, not a flaky test.

## Cost and cadence

The mock subset is free and runs on every push. The full suite makes roughly one model call per
case plus repairs (about 80 to 200 calls); run it nightly and before changing the model, prompt, or
schema. `--limit` and `--ids` keep local iteration cheap.
