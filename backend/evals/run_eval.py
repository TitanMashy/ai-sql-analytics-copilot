"""Text-to-SQL evaluation runner.

    python -m evals.run_eval --provider mock --subset mock          # deterministic, every push
    python -m evals.run_eval --provider gemini                      # full suite, nightly
    python -m evals.run_eval --check-references                     # validate the dataset itself

It asks every golden question through the real generation pipeline (schema context, provider,
validator, repair loop, executor) against a migrated and seeded PostgreSQL database, scores the
answers (see ``evals/scoring.py``), prints a summary, writes a JSON report (and optionally a
Markdown summary and a trend line), and exits non-zero when a threshold in
``evals/thresholds.json`` is missed. See ``docs/evaluation.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


class MeteredProvider:
    """Wraps a provider to estimate token usage without changing its behavior."""

    def __init__(self, provider: Any, prompt_builder: Any) -> None:
        self._provider = provider
        self._prompt_builder = prompt_builder
        self.name = provider.name
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
        return result

    @staticmethod
    def _kind(case: dict[str, Any]) -> str:
        if "adversarial" in case:
            return "adversarial"
        return "structure" if case["compare"] == "structure" else "accuracy"

    # -- scoring -----------------------------------------------------------------------------

    def _score_adversarial(self, case, asked, error, result: CaseResult) -> None:
        if error is not None:
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


def summarize(results: list[CaseResult], input_cost: float, output_cost: float) -> dict[str, Any]:
    scored = [item for item in results if item.kind in {"accuracy", "structure"}]
    adversarial = [item for item in results if item.kind == "adversarial"]
    latencies = [item.latency_ms for item in results]
    passed = sum(1 for item in scored if item.passed)
    tokens_in = sum(item.tokens_in for item in results)
    tokens_out = sum(item.tokens_out for item in results)
    categories: dict[str, dict[str, int]] = {}
    for item in scored:
        bucket = categories.setdefault(item.category, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(item.passed)
    return {
        "cases": len(results),
        "scored_cases": len(scored),
        "passed_cases": passed,
        "execution_accuracy": round(passed / len(scored), 4) if scored else 0.0,
        "validation_failure_rate": round(
            sum(item.validation_failed for item in scored) / len(scored), 4
        )
        if scored
        else 0.0,
        "repair_rate": round(sum(item.repaired for item in scored) / len(scored), 4)
        if scored
        else 0.0,
        "p50_latency_ms": round(percentile(latencies, 0.50), 1),
        "p95_latency_ms": round(percentile(latencies, 0.95), 1),
        "adversarial_cases": len(adversarial),
        "adversarial_leaks": sum(item.leaked for item in adversarial),
        "adversarial_rejected": sum(item.rejected for item in adversarial),
        "reference_failures": sum(item.reference_failed for item in results),
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
    lines = [
        f"## Text-to-SQL evaluation ({report['provider']}, {report['subset']})",
        "",
        f"Run at {report['generated_at']}; {summary['cases']} cases.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Execution accuracy | {summary['execution_accuracy']:.1%} "
        f"({summary['passed_cases']}/{summary['scored_cases']}) |",
        f"| Validation failure rate | {summary['validation_failure_rate']:.1%} |",
        f"| Repair rate | {summary['repair_rate']:.1%} |",
        f"| Latency p50 / p95 | {summary['p50_latency_ms']} ms / {summary['p95_latency_ms']} ms |",
        f"| Adversarial leaks | {summary['adversarial_leaks']} of {summary['adversarial_cases']} |",
        f"| Adversarial rejected outright | {summary['adversarial_rejected']} |",
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
        lines += ["", "### Failures", "", "| Case | Reason |", "|---|---|"]
        lines += [f"| {item['id']} | {item['reason'] or item['error_code']} |" for item in failures]
    if report["violations"]:
        lines += ["", "### Threshold violations", ""]
        lines += [f"- {message}" for message in report["violations"]]
    return "\n".join(lines) + "\n"


# -- entry point ----------------------------------------------------------------------------


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
    parser.add_argument("--provider", choices=["mock", "gemini"], default="mock")
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
    os.environ["LLM_MODE"] = args.provider

    from app.analytics.dependencies import get_analytics_query_service
    from app.conversation.service import ConversationMemory
    from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal
    from app.core.config import get_settings
    from app.core.metrics import metrics
    from app.llm.prompt import SQLPromptBuilder
    from app.services.generation import SQLGenerationService
    from app.services.llm_dependencies import get_llm_provider

    settings = get_settings()
    if settings.is_production:
        print("Refusing to run evaluations with APP_ENV=production.", file=sys.stderr)
        return 2
    analytics = get_analytics_query_service()
    principal = Principal("evaluation", roles=(ANALYTICS_ADMIN_ROLE,))
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

    provider = MeteredProvider(get_llm_provider(), SQLPromptBuilder())
    service = SQLGenerationService(
        provider,  # type: ignore[arg-type]
        analytics_service=analytics,
        max_repair_retries=settings.max_repair_retries,
        conversation_memory=ConversationMemory(),
        request_deadline_seconds=settings.request_deadline_seconds,
    )
    evaluator = Evaluator(service, analytics, principal, metrics, provider)
    results = evaluator.run(cases)

    summary = summarize(results, args.input_cost_per_million, args.output_cost_per_million)
    limits = json.loads(args.thresholds.read_text(encoding="utf-8"))
    violations = check_thresholds(summary, limits.get(args.provider, limits.get("default", {})))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": args.provider,
        "subset": args.subset,
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
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
