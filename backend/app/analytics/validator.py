import logging
from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.db.schema_metadata import get_schema_metadata

logger = logging.getLogger(__name__)

ALLOWED_TABLES = frozenset(
    {
        "customers",
        "users",
        "vehicles",
        "drivers",
        "trips",
        "vehicle_locations",
        "fuel_records",
        "maintenance_records",
        "invoices",
        "payments",
        "subscriptions",
    }
)
SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})
DANGEROUS_FUNCTIONS = frozenset(
    {
        "dblink",
        "dblink_connect",
        "lo_export",
        "lo_import",
        "pg_execute_server_program",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_ls_dir",
        "pg_sleep",
        "query_to_xml",
        "set_config",
        "xpath",
    }
)
FORBIDDEN_NODE_KEYS = frozenset(
    {
        "alter",
        "comment",
        "commit",
        "create",
        "delete",
        "drop",
        "grant",
        "insert",
        "into",
        "lock",
        "merge",
        "revoke",
        "rollback",
        "set",
        "transaction",
        "truncate",
        "update",
    }
)


@dataclass(frozen=True)
class QueryComplexity:
    joins: int
    subqueries: int
    nesting: int
    estimated_risk: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "joins": self.joins,
            "subqueries": self.subqueries,
            "nesting": self.nesting,
            "estimated_risk": self.estimated_risk,
        }


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    normalized_sql: str | None
    errors: list[str]
    warnings: list[str]
    tables: list[str]
    complexity: QueryComplexity
    error_code: str = "QUERY_VALIDATION_ERROR"
    repairable: bool = False


class SQLValidator:
    """AST-backed read-only validator for the explicit analytics table surface."""

    def __init__(
        self,
        max_result_rows: int = 1000,
        max_query_joins: int = 5,
        max_query_nesting: int = 3,
    ) -> None:
        self.max_result_rows = max_result_rows
        self.max_query_joins = max_query_joins
        self.max_query_nesting = max_query_nesting
        metadata = get_schema_metadata()
        self.table_columns = {
            table.name: {column.name for column in table.columns} for table in metadata
        }

    def validate(self, sql: str) -> ValidationResult:
        empty_complexity = QueryComplexity(0, 0, 0, "low")
        if not sql.strip():
            return ValidationResult(
                False,
                None,
                ["SQL query cannot be empty."],
                [],
                [],
                empty_complexity,
            )

        try:
            statements = parse(sql, read="postgres")
        except ParseError:
            logger.info("analytics SQL parse failed")
            return ValidationResult(
                False,
                None,
                ["SQL could not be parsed as PostgreSQL."],
                [],
                [],
                empty_complexity,
                error_code="QUERY_PARSE_ERROR",
                repairable=True,
            )

        if len(statements) != 1:
            return ValidationResult(
                False,
                None,
                ["Multiple SQL statements are not permitted."],
                [],
                [],
                empty_complexity,
                error_code="QUERY_SECURITY_ERROR",
            )

        expression = statements[0]
        cte_names = {cte.alias_or_name.casefold() for cte in expression.find_all(exp.CTE)}
        tables = [table for table in self._table_references(expression) if table not in cte_names]
        joins = len(list(expression.find_all(exp.Join)))
        subqueries = len(list(expression.find_all(exp.Subquery)))
        nesting = self._nesting_depth(expression)
        complexity = QueryComplexity(
            joins, subqueries, nesting, self._risk(joins, subqueries, nesting)
        )
        warnings: list[str] = []
        errors: list[str] = []
        error_code = "QUERY_VALIDATION_ERROR"
        repairable = False

        if expression.key not in {"select", "union", "intersect", "except"}:
            errors.append("Only SELECT statements are permitted.")
            error_code = "QUERY_SECURITY_ERROR"

        forbidden_nodes = [node for node in expression.walk() if node.key in FORBIDDEN_NODE_KEYS]
        if forbidden_nodes:
            errors.append("Write, DDL, and transaction operations are not permitted.")
            error_code = "QUERY_SECURITY_ERROR"

        unknown_tables = [
            table for table in tables if table not in ALLOWED_TABLES and table not in cte_names
        ]
        if unknown_tables:
            errors.append(f"Unknown or disallowed table reference: {unknown_tables[0]}.")
            if error_code != "QUERY_SECURITY_ERROR":
                error_code = "QUERY_VALIDATION_ERROR"
                repairable = True

        if self._system_table_references(expression):
            errors.append("System and catalog tables are not available to analytics queries.")
            error_code = "QUERY_SECURITY_ERROR"
            repairable = False

        if self._dangerous_functions(expression):
            errors.append("The query uses a restricted PostgreSQL function.")
            error_code = "QUERY_SECURITY_ERROR"
            repairable = False

        if joins > self.max_query_joins:
            errors.append(f"Query exceeds the maximum of {self.max_query_joins} joins.")
            if error_code != "QUERY_SECURITY_ERROR":
                error_code = "QUERY_COMPLEXITY_ERROR"
        if nesting > self.max_query_nesting:
            errors.append(f"Query exceeds the maximum nesting depth of {self.max_query_nesting}.")
            if error_code != "QUERY_SECURITY_ERROR":
                error_code = "QUERY_COMPLEXITY_ERROR"
        if self._has_cartesian_join(expression):
            errors.append("Cartesian joins are not permitted.")
            if error_code != "QUERY_SECURITY_ERROR":
                error_code = "QUERY_COMPLEXITY_ERROR"

        limit_value = self._limit_value(expression)
        if limit_value is not None and limit_value > self.max_result_rows:
            errors.append(f"LIMIT cannot exceed {self.max_result_rows} rows.")
            error_code = "QUERY_SECURITY_ERROR"
        if self._selects_star(expression):
            warnings.append("SELECT * is allowed but selecting only needed columns is recommended.")
        warnings.append("Risk is an internal heuristic, not a security guarantee.")

        column_errors = self._column_errors(expression, cte_names)
        if column_errors:
            errors.extend(column_errors)
            if error_code != "QUERY_SECURITY_ERROR":
                error_code = "QUERY_VALIDATION_ERROR"
                repairable = True

        normalized_sql = expression.sql(dialect="postgres")
        return ValidationResult(
            not errors,
            normalized_sql,
            errors,
            warnings,
            sorted(set(tables)),
            complexity,
            error_code=error_code,
            repairable=repairable,
        )

    def _table_references(self, expression: exp.Expression) -> list[str]:
        return [table.name.casefold() for table in expression.find_all(exp.Table)]

    def _system_table_references(self, expression: exp.Expression) -> list[str]:
        result = []
        for table in expression.find_all(exp.Table):
            database = (table.db or "").casefold()
            catalog = (table.catalog or "").casefold()
            if (
                database in SYSTEM_SCHEMAS
                or catalog in SYSTEM_SCHEMAS
                or table.name.casefold().startswith("pg_")
            ):
                result.append(table.name)
        return result

    def _dangerous_functions(self, expression: exp.Expression) -> list[str]:
        result = []
        for node in expression.walk():
            name = getattr(node, "name", "")
            sql_name = node.sql_name().casefold() if hasattr(node, "sql_name") else ""
            if name.casefold() in DANGEROUS_FUNCTIONS or sql_name in DANGEROUS_FUNCTIONS:
                result.append(name or sql_name)
        return result

    def _column_errors(self, expression: exp.Expression, cte_names: set[str]) -> list[str]:
        aliases: dict[str, str] = {}
        referenced_tables = []
        cte_columns: dict[str, set[str]] = {}
        for cte in expression.find_all(exp.CTE):
            select = cte.this.find(exp.Select)
            if select is not None:
                cte_columns[cte.alias_or_name.casefold()] = {
                    projection.alias_or_name.casefold()
                    for projection in select.expressions
                    if projection.alias_or_name
                }
        for table in expression.find_all(exp.Table):
            table_name = table.name.casefold()
            if table_name in self.table_columns:
                aliases[(table.alias_or_name or table_name).casefold()] = table_name
                referenced_tables.append(table_name)
        known_aliases = set(aliases) | cte_names
        select_aliases = {
            alias.alias_or_name.casefold()
            for alias in expression.find_all(exp.Alias)
            if alias.alias_or_name
        }
        errors = []
        for column in expression.find_all(exp.Column):
            column_name = column.name.casefold()
            if column_name == "*" or column_name in select_aliases:
                continue
            qualifier = (column.table or "").casefold()
            if qualifier and qualifier not in known_aliases:
                errors.append(f"Unknown table alias: {qualifier}.")
                continue
            if qualifier in cte_names:
                continue
            candidates = [aliases[qualifier]] if qualifier else referenced_tables
            known_cte_column = any(column_name in columns for columns in cte_columns.values())
            if (
                candidates
                and not known_cte_column
                and not any(column_name in self.table_columns[name] for name in candidates)
            ):
                errors.append(f"Unknown column reference: {column_name}.")
        return sorted(set(errors))

    def _limit_value(self, expression: exp.Expression) -> int | None:
        limit = expression.find(exp.Limit)
        if (
            limit is None
            or not isinstance(limit.expression, exp.Literal)
            or not limit.expression.is_int
        ):
            return None
        return int(limit.expression.this)

    def _has_cartesian_join(self, expression: exp.Expression) -> bool:
        return any(
            str(join.args.get("kind") or "").casefold() == "cross"
            or (join.args.get("on") is None and not join.args.get("using"))
            for join in expression.find_all(exp.Join)
        )

    def _selects_star(self, expression: exp.Expression) -> bool:
        return any(column.name == "*" for column in expression.find_all(exp.Column))

    def _nesting_depth(self, expression: exp.Expression) -> int:
        depths = []
        for node in expression.find_all(exp.Subquery):
            depth = 0
            parent = node.parent
            while parent is not None:
                if isinstance(parent, exp.Subquery):
                    depth += 1
                parent = parent.parent
            depths.append(depth + 1)
        return max(depths, default=0)

    @staticmethod
    def _risk(joins: int, subqueries: int, nesting: int) -> str:
        score = joins + (subqueries * 2) + nesting
        if score >= 8:
            return "high"
        if score >= 4:
            return "medium"
        return "low"
