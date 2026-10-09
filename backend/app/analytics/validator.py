import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from app.db.analytics_surface import ANALYTICS_SCHEMA, PII_COLUMNS
from app.db.schema_metadata import get_schema_metadata

logger = logging.getLogger(__name__)

# Derived from the schema metadata so the allowlist cannot drift from the analytics surface.
ALLOWED_TABLES = frozenset(table.name for table in get_schema_metadata())
SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})

# Functions that are never acceptable, even if a future allowlist edit were to name them.
DANGEROUS_FUNCTIONS = frozenset(
    {
        "current_setting",
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
        "version",
        "xpath",
    }
)
DANGEROUS_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "inet_", "txid_")


def _normalize_function_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


# Only these functions may appear in analytics SQL. Names are compared after removing
# punctuation and case, so ``DATE_TRUNC``, ``DateTrunc`` and ``TimestampTrunc`` all match
# regardless of how SQLGlot names the node. Adding a function is a deliberate edit here.
ALLOWED_FUNCTIONS = frozenset(
    {
        # aggregates
        "COUNT",
        "SUM",
        "AVG",
        "MIN",
        "MAX",
        "STDDEV",
        "STDDEVPOP",
        "STDDEVSAMP",
        "VARIANCE",
        "VARPOP",
        "VARSAMP",
        "MEDIAN",
        "PERCENTILECONT",
        "PERCENTILEDISC",
        "STRINGAGG",
        "GROUPCONCAT",
        # date and time
        "DATETRUNC",
        "TIMESTAMPTRUNC",
        "DATEPART",
        "EXTRACT",
        "DATE",
        "DATEADD",
        "DATESUB",
        "DATEDIFF",
        "CURRENTDATE",
        "CURRENTTIMESTAMP",
        "CURRENTTIME",
        "NOW",
        "AGE",
        "TOCHAR",
        "TIMETOSTR",
        # math
        "ROUND",
        "CEIL",
        "CEILING",
        "FLOOR",
        "ABS",
        "POWER",
        "POW",
        "SQRT",
        "LN",
        "LOG",
        "EXP",
        "MOD",
        "SIGN",
        "TRUNC",
        "GREATEST",
        "LEAST",
        # conditional and casting
        "CASE",
        "COALESCE",
        "NULLIF",
        "CAST",
        "TRYCAST",
        "IF",
        # strings
        "LOWER",
        "UPPER",
        "LENGTH",
        "CONCAT",
        "CONCATWS",
        "TRIM",
        "LTRIM",
        "RTRIM",
        "SUBSTRING",
        "SUBSTR",
        "REPLACE",
        "LEFT",
        "RIGHT",
        "INITCAP",
        "SPLITPART",
        # window functions
        "ROWNUMBER",
        "RANK",
        "DENSERANK",
        "PERCENTRANK",
        "CUMEDIST",
        "NTILE",
        "LAG",
        "LEAD",
        "FIRSTVALUE",
        "LASTVALUE",
        "NTHVALUE",
        # predicates that SQLGlot models as functions
        "EXISTS",
        "ANY",
        "ALL",
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
    limit_enforced: bool = False


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
        try:
            return self._validate(sql)
        except RecursionError:
            # Parsing can succeed on deeply nested input that is too deep to walk or regenerate.
            return ValidationResult(
                False,
                None,
                ["SQL is too deeply nested."],
                [],
                [],
                QueryComplexity(0, 0, 0, "high"),
                error_code="QUERY_COMPLEXITY_ERROR",
            )

    def _validate(self, sql: str) -> ValidationResult:
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
        except (SqlglotError, RecursionError):
            # ParseError, TokenError (unterminated strings, stray characters), and pathologically
            # nested input all mean "this is not SQL we will run".
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

        # ``;;`` and a trailing ``;`` yield empty entries; they are not statements.
        parsed = [statement for statement in statements if statement is not None]
        if not parsed:
            return ValidationResult(
                False,
                None,
                ["SQL query cannot be empty."],
                [],
                [],
                empty_complexity,
            )
        if len(parsed) != 1:
            return ValidationResult(
                False,
                None,
                ["Multiple SQL statements are not permitted."],
                [],
                [],
                empty_complexity,
                error_code="QUERY_SECURITY_ERROR",
            )

        expression = parsed[0]
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
        elif any(
            isinstance(node, exp.Select) and not node.expressions for node in expression.walk()
        ):
            # sqlglot accepts a bare ``SELECT`` (also as a subquery, or after ``FROM``); the LIMIT
            # rewrite would then emit invalid SQL.
            errors.append("Every SELECT must select at least one column.")
            repairable = True

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

        if self._has_schema_qualifier(expression):
            errors.append(
                "Schema-qualified table references are not permitted; use plain table names."
            )
            if error_code != "QUERY_SECURITY_ERROR":
                repairable = True

        restricted_functions, unsupported_functions = self._function_violations(expression)
        if restricted_functions:
            errors.append("The query uses a restricted PostgreSQL function.")
            error_code = "QUERY_SECURITY_ERROR"
        if unsupported_functions:
            errors.append(
                f"Function {unsupported_functions[0]} is not available in analytics queries; "
                "use standard aggregate, date, math, or string functions."
            )
            if error_code != "QUERY_SECURITY_ERROR":
                repairable = True

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

        if self._selects_star(expression):
            warnings.append("SELECT * is allowed but selecting only needed columns is recommended.")
        warnings.append("Risk is an internal heuristic, not a security guarantee.")

        column_errors, personal_data_errors = self._column_errors(expression, cte_names)
        if personal_data_errors:
            errors.extend(personal_data_errors)
            error_code = "QUERY_SECURITY_ERROR"
        if column_errors:
            errors.extend(column_errors)
            if error_code != "QUERY_SECURITY_ERROR":
                error_code = "QUERY_VALIDATION_ERROR"
                repairable = True

        if error_code == "QUERY_SECURITY_ERROR":
            repairable = False

        limit_enforced = False
        if not errors:
            limit_enforced, limit_warning = self._enforce_limit(expression)
            if limit_warning:
                warnings.append(limit_warning)

        # Comments are dropped: they carry nothing the database needs, and some are not
        # re-parseable once the statement has been rewritten.
        normalized_sql = expression.sql(dialect="postgres", comments=False)
        return ValidationResult(
            not errors,
            normalized_sql,
            errors,
            warnings,
            sorted(set(tables)),
            complexity,
            error_code=error_code,
            repairable=repairable,
            limit_enforced=limit_enforced,
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

    @staticmethod
    def _has_schema_qualifier(expression: exp.Expression) -> bool:
        """True for any qualifier other than the analytics schema (system schemas excluded).

        System schemas are reported separately as a security error.
        """
        for table in expression.find_all(exp.Table):
            database = (table.db or "").casefold()
            catalog = (table.catalog or "").casefold()
            if catalog and catalog not in SYSTEM_SCHEMAS:
                return True
            if database and database != ANALYTICS_SCHEMA and database not in SYSTEM_SCHEMAS:
                return True
        return False

    @staticmethod
    def _function_violations(expression: exp.Expression) -> tuple[list[str], list[str]]:
        """Split function calls into restricted (security) and merely unsupported ones."""
        restricted: list[str] = []
        unsupported: list[str] = []
        for node in expression.walk():
            if not isinstance(node, exp.Func):
                continue
            if isinstance(node, exp.Connector):
                # AND / OR / XOR are boolean operators. Some sqlglot releases also type them as
                # ``Func``, which would make the allowlist reject every compound WHERE clause.
                continue
            if isinstance(node, exp.Anonymous):
                display = str(node.name or "")
                names = {display}
            else:
                display = type(node).__name__
                names = {display, node.key}
                try:
                    names.add(node.sql_name())
                except (AttributeError, NotImplementedError):
                    pass
            lowered = {name.casefold() for name in names if name}
            if lowered & DANGEROUS_FUNCTIONS or any(
                name.startswith(DANGEROUS_FUNCTION_PREFIXES) for name in lowered
            ):
                restricted.append(display)
            elif not any(_normalize_function_name(name) in ALLOWED_FUNCTIONS for name in names):
                unsupported.append(display)
        return restricted, unsupported

    @staticmethod
    def _derived_tables(expression: exp.Expression) -> tuple[set[str], set[str], bool]:
        """Aliases and output columns of ``FROM (SELECT ...) alias`` derived tables."""
        aliases: set[str] = set()
        columns: set[str] = set()
        has_star = False
        for subquery in expression.find_all(exp.Subquery):
            alias = subquery.alias
            if not alias:
                continue
            aliases.add(alias.casefold())
            inner = subquery.this
            select = inner.find(exp.Select) if isinstance(inner, exp.Expression) else None
            if select is None:
                has_star = True
                continue
            for projection in select.expressions:
                name = projection.alias_or_name
                if not name or name == "*":
                    has_star = True
                else:
                    columns.add(name.casefold())
        return aliases, columns, has_star

    def _column_errors(
        self, expression: exp.Expression, cte_names: set[str]
    ) -> tuple[list[str], list[str]]:
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
        derived_aliases, derived_columns, derived_has_star = self._derived_tables(expression)
        known_aliases = set(aliases) | cte_names | derived_aliases
        select_aliases = {
            alias.alias_or_name.casefold()
            for alias in expression.find_all(exp.Alias)
            if alias.alias_or_name
        }
        errors = []
        personal_data_errors = []
        for column in expression.find_all(exp.Column):
            column_name = column.name.casefold()
            if (
                column_name == "*"
                or column_name in select_aliases
                or column_name in derived_columns
            ):
                continue
            qualifier = (column.table or "").casefold()
            if qualifier and qualifier not in known_aliases:
                errors.append(f"Unknown table alias: {qualifier}.")
                continue
            if qualifier in cte_names or qualifier in derived_aliases:
                continue
            if not qualifier and derived_has_star:
                continue
            candidates = [aliases[qualifier]] if qualifier else referenced_tables
            if any(
                column_name in PII_COLUMNS.get(name, frozenset())
                and column_name not in self.table_columns[name]
                for name in candidates
            ):
                personal_data_errors.append(
                    f"Column {column_name} contains personal data and is not available."
                )
                continue
            known_cte_column = any(column_name in columns for columns in cte_columns.values())
            if (
                candidates
                and not known_cte_column
                and not any(column_name in self.table_columns[name] for name in candidates)
            ):
                errors.append(f"Unknown column reference: {column_name}.")
        return sorted(set(errors)), sorted(set(personal_data_errors))

    def _enforce_limit(self, expression: exp.Expression) -> tuple[bool, str | None]:
        """Cap the outermost query at ``max_result_rows + 1`` rows.

        One extra row lets the executor detect (and report) truncation while the database never
        computes more than that for plain selects. Only the outer limit is considered, so a
        ``LIMIT`` inside a subquery cannot mask a missing or oversized outer one.
        """
        limit = expression.args.get("limit")
        current: int | None = None
        if (
            isinstance(limit, exp.Limit)
            and isinstance(limit.expression, exp.Literal)
            and limit.expression.is_int
        ):
            current = int(limit.expression.this)
        if current is not None and current <= self.max_result_rows:
            return False, None
        expression.set("limit", exp.Limit(expression=exp.Literal.number(self.max_result_rows + 1)))
        if limit is None:
            return True, f"No LIMIT clause; results are capped at {self.max_result_rows} rows."
        return True, f"LIMIT was reduced to the maximum of {self.max_result_rows} rows."

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
