"""Text-to-SQL evaluation runner.

    python -m evals.run_eval --provider mock --subset mock          # deterministic, every push
    python -m evals.run_eval --provider gemini                      # full suite, nightly
    python -m evals.run_eval --provider ollama --model llama3.1:8b  # a local model
    python -m evals.run_eval --check-references                     # validate the dataset itself

It asks every golden question through the real generation pipeline (schema context, provider,
validator, repair loop, executor) against a migrated and seeded PostgreSQL database, scores the
answers (see ``evals/scoring.py``), prints a summary, writes a JSON report (and optionally a
Markdown summary and a trend line), and exits non-zero when a threshold in
``evals/thresholds.json`` is missed. Exit codes: 0 passed, 1 a threshold was missed, 2 bad
configuration, 3 blocked (every request failed in the model path, so nothing was measured).
See ``docs/evaluation.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.llm_tracing import configure_llm_tracing, flush_llm_tracing, trace_case
from evals.scoring import (
    check_adversarial,
    check_structure,
    compare_results,
    percentile,
)

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "golden_questions.json"
DEFAULT_THRESHOLDS = HERE / "thresholds.json"
CHARS_PER_TOKEN = 4  # rough estimate; providers do not report usage through the common interface


# What the error code of a failed request says about the *model path*, as opposed to the answer.
PROVIDER_ERROR_CODES = frozenset(
    {
        "LLM_TIMEOUT",
        "LLM_RATE_LIMITED",
        "LLM_CREDENTIALS_INVALID",
        "LLM_MODEL_UNAVAILABLE",
        "LLM_PROVIDER_UNAVAILABLE",
        "LLM_PROVIDER_ERROR",
        "LLM_CONFIGURATION_ERROR",
        "UNEXPECTED_PROVIDER_ERROR",
    }
)
DECLINED_CODES = frozenset({"MOCK_QUERY_UNSUPPORTED"})  # the mock refusing to answer
PARSE_FAILURE_CODES = frozenset({"INVALID_LLM_RESPONSE"})
DEADLINE_CODES = frozenset({"REQUEST_DEADLINE_EXCEEDED"})
SAFETY_REJECTION_CODES = frozenset(
    {
        "QUERY_SECURITY_ERROR",
        "QUERY_VALIDATION_ERROR",
        "QUERY_PARSE_ERROR",
        "QUERY_COMPLEXITY_ERROR",
        "QUERY_PERMISSION_ERROR",
        "QUERY_GENERATION_FAILED",  # repairs exhausted: the final SQL was still rejected
        "TABLE_NOT_FOUND",
    }
)
# Outcomes in which the safety layers (validation, execution controls) were never exercised.
NOT_EXERCISED = frozenset({"provider_error", "declined", "parse_failure", "deadline"})


OUTCOMES = (
    "provider_error",
    "declined",
    "parse_failure",
    "deadline",
    "safety_rejection",
    "execution_error",
)


def classify_error(code: str | None) -> str:
    """Name what a failed request tells us: a provider problem, a safety rejection, and so on."""
    if code is None:
        return "answered"
    if code in PROVIDER_ERROR_CODES:
        return "provider_error"
    if code in DECLINED_CODES:
        return "declined"
    if code in PARSE_FAILURE_CODES:
        return "parse_failure"
    if code in DEADLINE_CODES:
        return "deadline"
    if code in SAFETY_REJECTION_CODES:
        return "safety_rejection"
    return "execution_error"


@dataclass
class CaseResult:
    id: str
    category: str
    kind: str  # "accuracy", "structure", or "adversarial"
    passed: bool
    reason: str = ""
    latency_ms: float = 0.0
    validation_failed: bool = False
    repaired: bool = False
    leaked: bool = False
    rejected: bool = False
    error_code: str | None = None
    reference_failed: bool = False
    generated_sql: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    # How the request ended (see classify_error) and whether it produced an executed answer.
    outcome: str = ""
    answered: bool = False


class MeteredProvider:
    """Wraps a provider to estimate token usage without changing its behavior."""

    def __init__(self, provider: Any, prompt_builder: Any) -> None:
        self._provider = provider
        self._prompt_builder = prompt_builder
        self.name = provider.name
        self.model = getattr(provider, "model", None)
        self.tokens_in = 0
        self.tokens_out = 0

    def _meter_in(self, question: str, schema_context: Any, conversation_context: str | None):
        prompt = self._prompt_builder.build(question, schema_context, conversation_context)
        self.tokens_in += len(prompt) // CHARS_PER_TOKEN

    def _meter_out(self, generation: Any) -> None:
        self.tokens_out += (len(generation.sql) + len(generation.explanation)) // CHARS_PER_TOKEN

    def generate_sql(self, question, schema_context, conversation_context=None):
        self._meter_in(question, schema_context, conversation_context)
        generation = self._provider.generate_sql(question, schema_context, conversation_context)
        self._meter_out(generation)
        return generation

    def repair_sql(
        self, question, original_sql, error_message, schema_context, conversation_context=None
    ):
        self._meter_in(question, schema_context, conversation_context)
        self.tokens_in += (len(original_sql) + len(error_message)) // CHARS_PER_TOKEN
        generation = self._provider.repair_sql(
            question,
            original_sql,
            error_message,
            schema_context,
            conversation_context=conversation_context,
        )
        self._meter_out(generation)
        return generation


@dataclass
class Evaluator:
    """Runs cases against an ask-capable service and an execution service."""

    service: Any  # SQLGenerationService
    analytics: Any  # AnalyticsQueryService
    principal: Any
    metrics_source: Any  # app.core.metrics.metrics
    provider: MeteredProvider | None = None
    run_id: str = field(default_factory=lambda: str(int(time.time())))

    def run(self, cases: list[dict[str, Any]]) -> list[CaseResult]:
        return [self.evaluate(case) for case in cases]

    # -- one case ----------------------------------------------------------------------------

    def evaluate(self, case: dict[str, Any]) -> CaseResult:
        conversation_id = f"eval-{self.run_id}-{case['id']}"
        for earlier_question in case.get("history", []):
            try:
                self.service.ask(
                    earlier_question, conversation_id=conversation_id, principal=self.principal
                )
            except Exception:  # noqa: BLE001 - history is setup; only the final answer is scored
                pass

        before = self.metrics_source.snapshot()
        tokens_before = (
            (self.provider.tokens_in, self.provider.tokens_out) if self.provider else (0, 0)
        )
        started_at = time.perf_counter()
        asked = None
        error: Exception | None = None
        try:
            with trace_case(case["id"]):
                asked = self.service.ask(
                    case["question"], conversation_id=conversation_id, principal=self.principal
                )
        except Exception as exc:  # noqa: BLE001 - any failure is a scored outcome
            error = exc
        latency_ms = (time.perf_counter() - started_at) * 1000
        after = self.metrics_source.snapshot()

        result = CaseResult(
            id=case["id"],
            category=case["category"],
            kind=self._kind(case),
            passed=False,
            latency_ms=round(latency_ms, 1),
            validation_failed=after["validation_failures_total"]
            > before["validation_failures_total"],
            repaired=after["sql_repair_attempts_total"] > before["sql_repair_attempts_total"],
            error_code=getattr(error, "code", type(error).__name__) if error else None,
            generated_sql=asked.generated.sql if asked else None,
            answered=asked is not None,
        )
        if self.provider:
            result.tokens_in = self.provider.tokens_in - tokens_before[0]
            result.tokens_out = self.provider.tokens_out - tokens_before[1]

        if "adversarial" in case:
            self._score_adversarial(case, asked, error, result)
        elif case["compare"] == "structure":
            self._score_structure(case, asked, error, result)
        else:
            self._score_accuracy(case, asked, error, result)
        result.outcome = self._outcome(result)
        return result

    @staticmethod
    def _outcome(result: CaseResult) -> str:
        if result.kind == "adversarial":
            if result.leaked:
                return "leaked"
            if result.error_code is None:
                return "answered_safely"
            kind = classify_error(result.error_code)
            return "inconclusive" if kind in NOT_EXERCISED else "rejected"
        if result.error_code is not None:
            return classify_error(result.error_code)
        if result.reference_failed:
            return "reference_failed"
        return "correct" if result.passed else "incorrect"

    @staticmethod
    def _kind(case: dict[str, Any]) -> str:
        if "adversarial" in case:
            return "adversarial"
        return "structure" if case["compare"] == "structure" else "accuracy"

    # -- scoring -----------------------------------------------------------------------------

    def _score_adversarial(self, case, asked, error, result: CaseResult) -> None:
        if error is not None:
            if classify_error(result.error_code) in NOT_EXERCISED:
                # The model path failed or declined, so the safety layers never saw this prompt.
                # That is neither a pass nor a rejection: report it as inconclusive.
                result.passed = False
                result.reason = f"inconclusive: the provider did not answer ({result.error_code})"
                return
            result.passed = True
            result.rejected = True
            result.reason = f"rejected ({result.error_code})"
            return
        finding = check_adversarial(
            case["adversarial"],
            asked.generated.sql,
            asked.result.columns,
            asked.result.rows,
            [asked.generated.explanation, asked.summary or ""],
        )
        result.leaked = finding.leaked
        result.passed = not finding.leaked
        result.reason = "; ".join(finding.reasons) if finding.leaked else "answered safely"

    def _score_structure(self, case, asked, error, result: CaseResult) -> None:
        if error is not None:
            result.reason = f"request failed ({result.error_code})"
            return
        outcome = check_structure(
            case.get("expect", {}),
            asked.result.columns,
            asked.result.rows,
            asked.generated.tables_used,
        )
        result.passed = outcome.passed
        result.reason = "; ".join(outcome.reasons)

    def _score_accuracy(self, case, asked, error, result: CaseResult) -> None:
        if error is not None:
            result.reason = f"request failed ({result.error_code})"
            return
        references = [case["reference_sql"], *case.get("alternatives", [])]
        reasons: list[str] = []
        for reference_sql in references:
            try:
                expected = self.analytics.execute(reference_sql, principal=self.principal)
            except Exception as exc:  # noqa: BLE001
                result.reference_failed = True
                code = getattr(exc, "code", type(exc).__name__)
                result.reason = f"reference query failed ({code})"
                return
            matches, reason = compare_results(
                case["compare"],
                expected.columns,
                expected.rows,
                asked.result.columns,
                asked.result.rows,
            )
            if matches:
                result.passed = True
                return
            reasons.append(reason)
        result.reason = reasons[0] if reasons else "no reference to compare with"


# -- aggregation and thresholds -------------------------------------------------------------


def summarize(
    results: list[CaseResult],
    input_cost: float,
    output_cost: float,
    dataset_cases: int | None = None,
) -> dict[str, Any]:
    scored = [item for item in results if item.kind in {"accuracy", "structure"}]
    adversarial = [item for item in results if item.kind == "adversarial"]
    latencies = [item.latency_ms for item in results]
    passed = sum(1 for item in scored if item.passed)
    answered = [item for item in scored if item.answered]
    tokens_in = sum(item.tokens_in for item in results)
    tokens_out = sum(item.tokens_out for item in results)
    # Bucket by the underlying error code, so an adversarial case that failed because the
    # provider was down is counted as a provider failure, not only as "inconclusive".
    outcomes = {
        name: sum(1 for item in results if classify_error(item.error_code) == name)
        for name in OUTCOMES
    }
    categories: dict[str, dict[str, int]] = {}
    for item in scored:
        bucket = categories.setdefault(item.category, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(item.passed)
    provider_errors = outcomes["provider_error"]
    first_error = next(
        (
            item.error_code
            for item in results
            if classify_error(item.error_code) == "provider_error"
        ),
        None,
    )
    return {
        # How much of the dataset this run covers. A case that was not run is not a pass.
        "dataset_cases": dataset_cases if dataset_cases is not None else len(results),
        "cases": len(results),
        "not_run_cases": (dataset_cases - len(results)) if dataset_cases is not None else 0,
        "scored_cases": len(scored),
        "unscored_cases": len(adversarial),
        "passed_cases": passed,
        # Semantic correctness over every scored case; provider failures count as wrong.
        "execution_accuracy": round(passed / len(scored), 4) if scored else 0.0,
        # SQL validity: the share of scored cases that ended in SQL that was accepted and executed.
        "answered_cases": len(answered),
        "valid_sql_rate": round(len(answered) / len(scored), 4) if scored else 0.0,
        # Correctness only among the answers that were produced.
        "accuracy_of_answered": round(passed / len(answered), 4) if answered else 0.0,
        "validation_failure_rate": round(
            sum(item.validation_failed for item in scored) / len(scored), 4
        )
        if scored
        else 0.0,
        "repair_rate": round(sum(item.repaired for item in scored) / len(scored), 4)
        if scored
        else 0.0,
        "repaired_cases": sum(item.repaired for item in results),
        "provider_error_cases": provider_errors,
        "declined_cases": outcomes["declined"],
        "parse_failure_cases": outcomes["parse_failure"],
        "deadline_cases": outcomes["deadline"],
        "safety_rejected_cases": outcomes["safety_rejection"],
        "execution_error_cases": outcomes["execution_error"],
        "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "p50_latency_ms": round(percentile(latencies, 0.50), 1),
        "p95_latency_ms": round(percentile(latencies, 0.95), 1),
        "adversarial_cases": len(adversarial),
        "adversarial_leaks": sum(item.leaked for item in adversarial),
        "adversarial_rejected": sum(item.rejected for item in adversarial),
        # The provider failed or declined, so the safety layers never saw the prompt.
        "adversarial_inconclusive": sum(item.outcome == "inconclusive" for item in adversarial),
        "reference_failures": sum(item.reference_failed for item in results),
        # Every request failed in the model path: report the run as blocked, not as a result.
        "blocked": bool(results) and provider_errors == len(results),
        "blocked_reason": first_error if results and provider_errors == len(results) else None,
        "tokens_in_estimate": tokens_in,
        "tokens_out_estimate": tokens_out,
        "cost_estimate_usd": round(
            tokens_in / 1_000_000 * input_cost + tokens_out / 1_000_000 * output_cost, 4
        ),
        "by_category": {
            name: {**counts, "accuracy": round(counts["passed"] / counts["total"], 4)}
            for name, counts in sorted(categories.items())
        },
    }


def check_thresholds(summary: dict[str, Any], limits: dict[str, Any]) -> list[str]:
    """Return one message per missed threshold. ``null`` limits are recorded but not enforced."""
    violations: list[str] = []
    checks = [
        ("execution_accuracy", "execution_accuracy_min", lambda value, limit: value < limit),
        ("validation_failure_rate", "validation_failure_rate_max", lambda v, limit: v > limit),
        ("repair_rate", "repair_rate_max", lambda value, limit: value > limit),
        ("p95_latency_ms", "p95_latency_ms_max", lambda value, limit: value > limit),
        ("adversarial_leaks", "adversarial_leaks_max", lambda value, limit: value > limit),
        ("reference_failures", "reference_failures_max", lambda value, limit: value > limit),
    ]
    for metric, key, failed in checks:
        limit = limits.get(key)
        if limit is None:
            continue
        if failed(summary[metric], limit):
            violations.append(f"{metric} = {summary[metric]} violates {key} = {limit}")
    return violations


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    model = report.get("model") or "-"
    lines = [f"## Text-to-SQL evaluation ({report['provider']}, {report['subset']})", ""]
    if summary.get("blocked"):
        lines += [
            f"**BLOCKED:** every request failed in the model path ({summary['blocked_reason']}). "
            "No accuracy figure below is a result about this provider; none was measured.",
            "",
        ]
    lines += [
        f"Run at {report['generated_at']}; provider `{report['provider']}`, model `{model}`.",
        f"{summary['cases']} cases run of {summary.get('dataset_cases', summary['cases'])} in the "
        f"dataset ({summary.get('not_run_cases', 0)} not run): {summary['scored_cases']} scored, "
        f"{summary['adversarial_cases']} adversarial (reported separately).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Execution accuracy (scored cases; provider failures count as wrong) | "
        f"{summary['execution_accuracy']:.1%} "
        f"({summary['passed_cases']}/{summary['scored_cases']}) |",
        f"| SQL accepted and executed (valid SQL rate) | "
        f"{summary.get('valid_sql_rate', 0.0):.1%} "
        f"({summary.get('answered_cases', 0)}/{summary['scored_cases']}) |",
        f"| Correct among the answers produced | {summary.get('accuracy_of_answered', 0.0):.1%} |",
        f"| Validation failure rate | {summary['validation_failure_rate']:.1%} |",
        f"| Repair rate | {summary['repair_rate']:.1%} "
        f"({summary.get('repaired_cases', 0)} cases) |",
        "| Provider errors / parse failures / deadline | "
        f"{summary.get('provider_error_cases', 0)}"
        f" / {summary.get('parse_failure_cases', 0)} / {summary.get('deadline_cases', 0)} |",
        f"| Provider declined to answer | {summary.get('declined_cases', 0)} |",
        "| Rejected by safety layers / execution errors | "
        f"{summary.get('safety_rejected_cases', 0)}"
        f" / {summary.get('execution_error_cases', 0)} |",
        f"| Latency mean / p50 / p95 | {summary.get('mean_latency_ms', 0)} ms / "
        f"{summary['p50_latency_ms']} ms / {summary['p95_latency_ms']} ms |",
        f"| Adversarial leaks | {summary['adversarial_leaks']} of {summary['adversarial_cases']} |",
        f"| Adversarial rejected by the safety layers | {summary['adversarial_rejected']} |",
        f"| Adversarial inconclusive (provider did not answer) | "
        f"{summary.get('adversarial_inconclusive', 0)} |",
        f"| Reference query failures | {summary['reference_failures']} |",
        f"| Tokens in / out (estimate) | {summary['tokens_in_estimate']} / "
        f"{summary['tokens_out_estimate']} |",
        f"| Cost estimate | ${summary['cost_estimate_usd']} |",
        "",
        "| Category | Passed | Accuracy |",
        "|---|---|---|",
    ]
    for name, counts in summary["by_category"].items():
        ratio = f"{counts['passed']}/{counts['total']}"
        lines.append(f"| {name} | {ratio} | {counts['accuracy']:.1%} |")
    failures = [item for item in report["results"] if not item["passed"]]
    if failures:
        lines += [
            "",
            "### Not passed (failed or inconclusive)",
            "",
            "| Case | Reason |",
            "|---|---|",
        ]
        lines += [f"| {item['id']} | {item['reason'] or item['error_code']} |" for item in failures]
    if report["violations"]:
        lines += ["", "### Threshold violations", ""]
        lines += [f"- {message}" for message in report["violations"]]
    context = []
    if report.get("settings"):
        settings = ", ".join(f"{key}={value}" for key, value in report["settings"].items())
        context.append(f"- Settings: {settings}")
    if report.get("environment"):
        environment = ", ".join(f"{key}={value}" for key, value in report["environment"].items())
        context.append(f"- Environment: {environment}")
    if report.get("provider_runtime"):
        runtime = json.dumps(report["provider_runtime"], sort_keys=True)
        context.append(f"- Provider runtime: {runtime}")
    if context:
        lines += ["", "### Run context", ""] + context
    return "\n".join(lines) + "\n"


# -- entry point ----------------------------------------------------------------------------


def count_dataset(path: Path) -> int:
    return len(json.loads(path.read_text(encoding="utf-8"))["cases"])


def _total_memory_gb() -> float | None:
    """Installed RAM in GiB, or None when it cannot be read cheaply."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            return round(int(out.stdout.strip()) / 2**30, 1)
        if sys.platform.startswith("linux"):
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong),
                    ("tpage", ctypes.c_ulonglong),
                    ("apage", ctypes.c_ulonglong),
                    ("tvirt", ctypes.c_ulonglong),
                    ("avirt", ctypes.c_ulonglong),
                    ("ext", ctypes.c_ulonglong),
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return round(status.total / 2**30, 1)
    except Exception:  # noqa: BLE001 - an environment note must never fail the run
        return None
    return None


def collect_environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        "memory_gb": _total_memory_gb(),
    }


def collect_settings(settings: Any) -> dict[str, Any]:
    """The configuration that shapes the answers. Never includes a key or a URL with credentials."""
    values: dict[str, Any] = {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.effective_llm_model,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "llm_max_retries": settings.llm_max_retries,
        "max_repair_retries": settings.max_repair_retries,
        "request_deadline_seconds": settings.request_deadline_seconds,
        "temperature": "0 (ignored by Gemini 3 models)",
    }
    if settings.llm_provider == "ollama":
        values["ollama_base_url"] = settings.ollama_base_url
    return values


def collect_provider_runtime(settings: Any) -> dict[str, Any] | None:
    """For Ollama: its version and what it has loaded (a resource observation), best effort."""
    if settings.llm_provider != "ollama":
        return None
    import httpx

    runtime: dict[str, Any] = {"available": False}
    try:
        base = settings.ollama_base_url
        version = httpx.get(f"{base}/api/version", timeout=3).json().get("version")
        loaded = httpx.get(f"{base}/api/ps", timeout=3).json().get("models", [])
        runtime = {
            "available": True,
            "version": version,
            "loaded_models": [
                {
                    "name": item.get("name"),
                    "size_gb": round(item.get("size", 0) / 2**30, 2),
                    "vram_gb": round(item.get("size_vram", 0) / 2**30, 2),
                }
                for item in loaded
            ],
        }
    except Exception:  # noqa: BLE001 - observation only
        pass
    return runtime


def load_cases(path: Path, subset: str, ids: list[str], limit: int | None) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    if subset == "mock":
        cases = [case for case in cases if case.get("mock")]
    if ids:
        cases = [case for case in cases if case["id"] in ids]
    return cases[:limit] if limit else cases


def check_references(cases: list[dict[str, Any]], analytics: Any, principal: Any) -> list[str]:
    """Execute every reference query; used to validate the dataset against a real database."""
    problems = []
    for case in cases:
        queries = [case.get("reference_sql"), *case.get("alternatives", [])]
        for sql in filter(None, queries):
            try:
                analytics.execute(sql, principal=principal)
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", type(exc).__name__)
                detail = getattr(exc, "repair_hint", None) or getattr(exc, "message", str(exc))
                problems.append(f"{case['id']}: {code}: {detail}")
    return problems


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the text-to-SQL evaluation suite.")
    parser.add_argument("--provider", choices=["mock", "gemini", "ollama"], default="mock")
    parser.add_argument("--model", help="model id; sets LLM_MODEL for this run")
    parser.add_argument("--subset", choices=["all", "mock"], default="all")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--ids", default="", help="comma-separated case ids to run")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--report", type=Path, default=Path("eval-report.json"))
    parser.add_argument("--markdown", type=Path, help="also write a Markdown summary")
    parser.add_argument("--trend", type=Path, help="append one summary line (JSONL) for trending")
    parser.add_argument("--input-cost-per-million", type=float, default=0.0)
    parser.add_argument("--output-cost-per-million", type=float, default=0.0)
    parser.add_argument("--check-references", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    # The provider is chosen through configuration, so set it before any app module reads it.
    os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    from app.analytics.dependencies import get_analytics_query_service
    from app.conversation.service import ConversationMemory
    from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal
    from app.core.config import ConfigurationError, get_settings
    from app.core.metrics import metrics
    from app.llm.prompt import SQLPromptBuilder
    from app.llm.provider import LLMProviderError
    from app.services.generation import SQLGenerationService
    from app.services.llm_dependencies import get_llm_provider

    try:
        settings = get_settings()
    except ConfigurationError as error:
        print(f"Cannot start the evaluation: {error}", file=sys.stderr)
        return 2
    if settings.is_production:
        print("Refusing to run evaluations with APP_ENV=production.", file=sys.stderr)
        return 2
    configure_llm_tracing(settings)
    analytics = get_analytics_query_service()
    principal = Principal("evaluation", roles=(ANALYTICS_ADMIN_ROLE,))
    dataset_total = count_dataset(args.cases)
    ids = [item for item in args.ids.split(",") if item]
    cases = load_cases(args.cases, args.subset, ids, args.limit)
    if not cases:
        print("No cases selected.", file=sys.stderr)
        return 2

    if args.check_references:
        problems = check_references(cases, analytics, principal)
        for problem in problems:
            print(f"FAIL {problem}")
        print(f"{len(cases)} cases checked, {len(problems)} reference problems")
        return 1 if problems else 0

    try:
        provider = MeteredProvider(get_llm_provider(), SQLPromptBuilder())
    except LLMProviderError as error:
        # A missing key or model is a configuration problem, not a result.
        print(f"Cannot start the evaluation: {error.code}: {error.message}", file=sys.stderr)
        return 2
    service = SQLGenerationService(
        provider,  # type: ignore[arg-type]
        analytics_service=analytics,
        max_repair_retries=settings.max_repair_retries,
        conversation_memory=ConversationMemory(),
        request_deadline_seconds=settings.request_deadline_seconds,
    )
    evaluator = Evaluator(service, analytics, principal, metrics, provider)
    results = evaluator.run(cases)

    summary = summarize(
        results, args.input_cost_per_million, args.output_cost_per_million, dataset_total
    )
    limits = json.loads(args.thresholds.read_text(encoding="utf-8"))
    violations = check_thresholds(summary, limits.get(args.provider, limits.get("default", {})))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": args.provider,
        "model": provider.model or settings.effective_llm_model,
        "subset": args.subset,
        "status": "blocked" if summary["blocked"] else "complete",
        "settings": collect_settings(settings),
        "environment": collect_environment(),
        "provider_runtime": collect_provider_runtime(settings),
        "summary": summary,
        "violations": violations,
        "results": [asdict(item) for item in results],
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.trend:
        line = {
            "generated_at": report["generated_at"],
            "provider": args.provider,
            "subset": args.subset,
            **{key: value for key, value in summary.items() if key != "by_category"},
        }
        with args.trend.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")

    print(render_markdown(report))
    flush_llm_tracing(10)
    if summary["blocked"]:
        return 3  # the provider never answered: not a pass, not a measured failure
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
