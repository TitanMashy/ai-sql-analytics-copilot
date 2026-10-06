import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.core.metrics import metrics


class PlanConnection:
    """Records EXPLAIN statements and answers with a canned plan."""

    def __init__(self, plan) -> None:
        self.plan = plan
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str):
        self.statements.append(statement)
        plan = self.plan

        class Result:
            @staticmethod
            def scalar():
                return plan

        return Result()


def _service(limit: float | None) -> AnalyticsQueryService:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    return AnalyticsQueryService(engine, query_cost_limit=limit)


def _plan(total_cost: float):
    return [{"Plan": {"Node Type": "Seq Scan", "Total Cost": total_cost}}]


def test_plans_within_the_budget_are_allowed() -> None:
    connection = PlanConnection(_plan(500.0))

    _service(1000)._check_query_cost(connection, "SELECT 1")

    assert connection.statements == ["EXPLAIN (FORMAT JSON) SELECT 1"]


def test_plans_over_the_budget_are_rejected_with_a_repair_hint() -> None:
    before = metrics.snapshot()["sql_execution_failures_total"]
    connection = PlanConnection(_plan(2_500_000.0))

    with pytest.raises(AnalyticsServiceError) as error:
        _service(1_000_000)._check_query_cost(connection, "SELECT 1")

    assert error.value.code == "QUERY_COST_EXCEEDED"
    assert error.value.status_code == 400
    assert error.value.repairable
    assert "2,500,000" in error.value.repair_hint
    assert "1,000,000" in error.value.repair_hint
    assert "2,500,000" not in error.value.message  # the public message carries no estimate
    assert metrics.snapshot()["sql_execution_failures_total"] == before + 1


def test_json_text_plans_are_parsed() -> None:
    connection = PlanConnection(json.dumps(_plan(9_999_999.0)))

    with pytest.raises(AnalyticsServiceError):
        _service(1000)._check_query_cost(connection, "SELECT 1")


def test_a_disabled_limit_skips_the_explain_round_trip() -> None:
    connection = PlanConnection(_plan(10**12))

    _service(None)._check_query_cost(connection, "SELECT 1")

    assert connection.statements == []


@pytest.mark.parametrize("plan", [None, [], [{}], [{"Plan": {}}], "not json at all"])
def test_an_unexpected_plan_shape_never_blocks_a_query(plan) -> None:
    _service(1000)._check_query_cost(PlanConnection(plan), "SELECT 1")


def test_percent_signs_reach_explain_already_escaped_for_the_driver() -> None:
    connection = PlanConnection(_plan(1.0))
    statement = AnalyticsQueryService._driver_sql(
        "SELECT 1 WHERE x LIKE 'a%'",
        type("C", (), {"dialect": type("D", (), {"paramstyle": "pyformat"})()})(),
    )

    _service(1000)._check_query_cost(connection, statement)

    assert connection.statements == ["EXPLAIN (FORMAT JSON) SELECT 1 WHERE x LIKE 'a%%'"]
