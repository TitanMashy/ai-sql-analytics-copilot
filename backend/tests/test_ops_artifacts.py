"""The operations artifacts (alerts, dashboard, runbooks, manifests) must match the code.

An alert on a metric the application does not export, or a runbook link that 404s, fails silently
in production. These tests make both a CI failure.
"""

import json
import re
from pathlib import Path

import pytest

from app.core.metrics import MetricsRegistry

ROOT = Path(__file__).resolve().parents[2]
ALERTS = ROOT / "ops" / "prometheus" / "alerts.yml"
SLO_RULES = ROOT / "ops" / "prometheus" / "slo-rules.yml"
DASHBOARD = ROOT / "ops" / "grafana" / "dashboard.json"
KUBERNETES = ROOT / "ops" / "kubernetes" / "analytics-backend.yaml"

METRIC = re.compile(r"\banalytics_[a-z0-9_]+")
RECORDED = re.compile(r"\banalytics:[a-z0-9_:]+")


def exported_metric_names() -> set[str]:
    """Every series name the registry can expose, derived from its own # TYPE lines."""
    exposition = MetricsRegistry().render_prometheus().decode()
    names: set[str] = set()
    for name, kind in re.findall(r"^# TYPE (\S+) (\w+)$", exposition, flags=re.MULTILINE):
        names.add(name)
        if kind == "histogram":
            names.update({f"{name}_bucket", f"{name}_count", f"{name}_sum"})
    return names


def recorded_rule_names() -> set[str]:
    return set(re.findall(r"^\s*- record: (\S+)", SLO_RULES.read_text(encoding="utf-8"), re.M))


def _metrics_in(text: str) -> set[str]:
    without_recorded = RECORDED.sub("", text)
    return set(METRIC.findall(without_recorded))


def test_every_alert_and_recording_rule_uses_a_metric_the_app_exports() -> None:
    exported = exported_metric_names()
    for path in (ALERTS, SLO_RULES):
        # Recording-rule names (analytics:...) are removed first; what remains is raw metrics.
        used = _metrics_in(path.read_text(encoding="utf-8"))
        missing = used - exported
        assert not missing, f"{path.name} uses metrics the app does not export: {sorted(missing)}"
        assert used, f"{path.name}: no metrics found; the extraction pattern is broken"


def test_alerts_only_use_recording_rules_that_exist() -> None:
    used = set(RECORDED.findall(ALERTS.read_text(encoding="utf-8")))

    assert used, "alerts should build on the SLI recording rules"
    assert used <= recorded_rule_names(), sorted(used - recorded_rule_names())


def test_every_alert_links_to_a_runbook_that_exists() -> None:
    text = ALERTS.read_text(encoding="utf-8")
    alerts = re.findall(r"- alert: (\w+)", text)
    runbooks = re.findall(r"^\s+runbook: (\S+)$", text, flags=re.MULTILINE)

    assert len(alerts) >= 10
    assert len(runbooks) == len(alerts), "every alert needs a runbook annotation"
    for runbook in runbooks:
        target = ROOT / runbook.split("#")[0]
        assert target.is_file(), f"{runbook} does not exist"
        if "#" in runbook:
            anchor = runbook.split("#")[1]
            headings = re.findall(r"^#+\s+(.+)$", target.read_text(encoding="utf-8"), re.MULTILINE)
            slugs = {
                re.sub(r"[^a-z0-9 -]", "", heading.lower()).strip().replace(" ", "-")
                for heading in headings
            }
            assert anchor in slugs, f"{runbook}: no heading for #{anchor}"


def test_required_runbooks_exist_and_follow_the_template() -> None:
    required = {
        "llm-provider-outage.md",
        "database-saturation.md",
        "rate-limit-storm.md",
        "suspected-data-leak.md",
        "credential-rotation.md",
    }
    directory = ROOT / "docs" / "runbooks"

    assert required <= {path.name for path in directory.glob("*.md")}
    for name in required:
        text = (directory / name).read_text(encoding="utf-8")
        for heading in ("Symptoms", "Impact", "Diagnose", "Mitigate", "Verify recovery"):
            assert f"## {heading}" in text, f"{name} is missing '## {heading}'"


def test_the_dashboard_is_valid_json_and_queries_real_metrics() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    exported = exported_metric_names()
    recorded = recorded_rule_names()
    expressions = [
        target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", [])
    ]

    assert dashboard["uid"] == "analytics-copilot"
    assert len(expressions) >= 15
    for expression in expressions:
        assert _metrics_in(expression) <= exported, expression
        assert set(RECORDED.findall(expression)) <= recorded, expression
    ids = [panel["id"] for panel in dashboard["panels"]]
    assert len(ids) == len(set(ids))


def test_slo_document_names_each_objective_and_its_recording_rule() -> None:
    text = (ROOT / "docs" / "slos.md").read_text(encoding="utf-8")

    for rule in (
        "analytics:ask_availability:ratio_rate5m",
        "analytics:ask_latency_seconds:p95_5m",
        "analytics:ask_answer_rate:ratio_rate1h",
    ):
        assert rule in text
        assert rule in recorded_rule_names()


def test_kubernetes_example_separates_liveness_from_readiness() -> None:
    text = KUBERNETES.read_text(encoding="utf-8")

    assert re.search(r"livenessProbe:\s*\n\s*httpGet: \{path: /health,", text)
    assert re.search(r"readinessProbe:\s*\n\s*httpGet: \{path: /health/ready,", text)
    assert "maxUnavailable: 0" in text
    assert "kind: CronJob" in text and "app.jobs.purge" in text
    assert "alembic" in text  # migrations run as a Job, not at startup


@pytest.mark.parametrize("name", ["backup_postgres.sh", "restore_postgres.sh", "restore_drill.sh"])
def test_data_operation_scripts_fail_fast_and_guard_the_live_database(name: str) -> None:
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    if name == "restore_postgres.sh":
        assert "CONFIRM_RESTORE_LIVE" in text
        assert 'TARGET="${2:-app_restore_drill}"' in text
