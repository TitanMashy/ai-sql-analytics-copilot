"""Fail when line coverage of the security-critical packages falls below its threshold.

    pytest --cov=app --cov-report=json -m "not integration and not fuzz"
    python scripts/check_coverage.py coverage.json

Thresholds apply to whole packages (not the repository average), so a well-covered utility module
cannot hide an untested validator. Raise them as the baseline improves; never lower them to make a
build pass. The figure is ``covered_lines`` over ``num_statements``: conventional line coverage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# package prefix -> minimum percentage. Set from the first measured baseline (see
# docs/operations.md, "Quality gates"); the starting values are deliberately conservative.
THRESHOLDS: dict[str, float] = {
    "app/analytics/": 85.0,
    "app/services/": 80.0,
    "app/llm/": 75.0,
}


def package_coverage(report: dict, prefix: str) -> tuple[int, int]:
    covered = total = 0
    for path, data in report["files"].items():
        if path.replace("\\", "/").startswith(prefix):
            summary = data["summary"]
            covered += summary["covered_lines"]
            total += summary["num_statements"]
    return covered, total


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    for prefix, minimum in THRESHOLDS.items():
        covered, total = package_coverage(report, prefix)
        if total == 0:
            failures.append(f"{prefix}: no measured statements (wrong --cov source?)")
            continue
        percentage = 100.0 * covered / total
        status = "ok" if percentage >= minimum else "FAIL"
        print(
            f"{status:4} {prefix:<16} {percentage:5.1f}% "
            f"(minimum {minimum:.0f}%, {total} statements)"
        )
        if percentage < minimum:
            failures.append(f"{prefix}: {percentage:.1f}% is below {minimum:.0f}%")
    for failure in failures:
        print(f"coverage gate: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
