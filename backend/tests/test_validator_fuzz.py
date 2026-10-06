"""Seeded, randomized tests for the SQL validator.

Three properties are checked over many generated inputs:

1. Mutating a known-bad statement without changing its meaning (keyword case, whitespace,
   comments) never makes it valid.
2. The same mutations never make a known-good statement invalid (no false rejections).
3. Arbitrary token soup and hostile strings never crash the validator, and anything it does accept
   is a single read-only SELECT over allowed tables with a bounded LIMIT.

``FUZZ_SEED`` fixes the sequence (CI uses a constant so failures reproduce); ``FUZZ_ITERATIONS``
scales the run (the scheduled job uses a much larger value). A failing assertion prints the seed
and the offending statement.
"""

import os
import random
import re

import pytest
from sqlglot import exp, parse

from app.analytics.validator import ALLOWED_TABLES, SQLValidator

SEED = int(os.environ.get("FUZZ_SEED", "20261006"))
ITERATIONS = int(os.environ.get("FUZZ_ITERATIONS", "300"))

pytestmark = pytest.mark.fuzz

KNOWN_BAD = [
    "DROP TABLE vehicles",
    "DELETE FROM vehicles",
    "UPDATE vehicles SET status = 'retired'",
    "INSERT INTO vehicles (id) VALUES (1)",
    "TRUNCATE vehicles",
    "GRANT SELECT ON vehicles TO PUBLIC",
    "SELECT pg_sleep(5)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT version()",
    "SELECT current_setting('app.scope')",
    "SELECT set_config('app.scope', 'global', false)",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM public.vehicles",
    "SELECT * FROM secret_table",
    "SELECT email FROM users",
    "SELECT license_number FROM drivers",
    "SELECT 1; SELECT 2",
    "SELECT 1; DROP TABLE vehicles",
    "SELECT * INTO copy_of_vehicles FROM vehicles",
    "SELECT * FROM vehicles FOR UPDATE",
    "WITH gone AS (DELETE FROM vehicles RETURNING *) SELECT * FROM gone",
    "SELECT generate_series(1, 1000000000)",
]

KNOWN_GOOD = [
    "SELECT COUNT(*) FROM vehicles",
    "SELECT status, COUNT(*) AS n FROM vehicles GROUP BY status ORDER BY n DESC",
    "SELECT id FROM vehicles WHERE status = 'active' LIMIT 25",
    (
        "SELECT c.company_name, SUM(i.total_amount) AS revenue FROM customers c "
        "JOIN invoices i ON i.customer_id = c.id GROUP BY c.company_name "
        "ORDER BY revenue DESC LIMIT 10"
    ),
    (
        "WITH totals AS (SELECT customer_id, SUM(total_amount) AS revenue FROM invoices "
        "GROUP BY customer_id) SELECT customer_id, revenue FROM totals"
    ),
    "SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS position FROM vehicles",
    "SELECT DATE_TRUNC('month', invoice_date) AS m, SUM(total_amount) FROM invoices GROUP BY m",
    "SELECT s.total FROM (SELECT COUNT(*) AS total FROM vehicles) s",
]

TOKEN_POOL = [
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "LIMIT", "JOIN", "ON", "AS", "AND", "OR",
    "UNION", "WITH", "DISTINCT", "HAVING", "(", ")", ",", ";", "*", "=", "<>", "1", "42", "'x'",
    "NULL", "COUNT(*)", "SUM(id)", "vehicles", "trips", "invoices", "customers", "users",
    "drivers", "payments", "secret_table", "pg_sleep(1)", "id", "status", "email", "name",
    "DROP", "DELETE", "UPDATE", "INSERT", "INTO", "--", "/*", "*/", "\"", "'", "\\", "\x00",
    "é", "🚗", "$$", "::int", "[", "]", "{", "}", "@", "#", "~", "||", "%", "?", ":name",
]

_WORD = re.compile(r"[A-Za-z_]+")


def _mutate(sql: str, rng: random.Random) -> str:
    """Change spelling, never meaning: keyword case, whitespace, and comments."""
    pieces = re.split(r"('[^']*')", sql)  # leave string literals untouched
    mutated: list[str] = []
    for index, piece in enumerate(pieces):
        if index % 2 == 1:  # a quoted literal
            mutated.append(piece)
            continue
        piece = _WORD.sub(lambda match: _recase(match.group(0), rng), piece)
        piece = re.sub(r" +", lambda _: _whitespace(rng), piece)
        mutated.append(piece)
    result = "".join(mutated)
    if rng.random() < 0.3:
        result = f"{_whitespace(rng)}{result}{_whitespace(rng)}"
    if rng.random() < 0.2:
        result += " -- trailing comment"
    return result


def _recase(word: str, rng: random.Random) -> str:
    choice = rng.random()
    if choice < 0.33:
        return word.upper()
    if choice < 0.66:
        return word.lower()
    return "".join(ch.upper() if rng.random() < 0.5 else ch.lower() for ch in word)


def _whitespace(rng: random.Random) -> str:
    return rng.choice([" ", "  ", "\n", "\t", " /* c */ ", "\n  ", " /**/ "])


def _assert_safe_acceptance(validator: SQLValidator, sql: str, context: str) -> None:
    result = validator.validate(sql)
    if not result.valid:
        return
    statements = parse(result.normalized_sql, read="postgres")
    assert len(statements) == 1, f"{context}: accepted multiple statements: {sql!r}"
    assert statements[0].key in {"select", "union", "intersect", "except"}, (
        f"{context}: accepted a non-SELECT: {sql!r}"
    )
    tables = {
        table.name.casefold() for table in statements[0].find_all(exp.Table) if table.name
    } - {cte.alias_or_name.casefold() for cte in statements[0].find_all(exp.CTE)}
    extra = tables - ALLOWED_TABLES
    assert not extra, f"{context}: accepted tables {extra}: {sql!r}"
    assert "LIMIT" in result.normalized_sql.upper(), f"{context}: no LIMIT: {sql!r}"


@pytest.fixture(scope="module")
def validator() -> SQLValidator:
    return SQLValidator(max_result_rows=1000, max_query_joins=5, max_query_nesting=3)


def test_known_bad_statements_stay_rejected_under_semantics_preserving_mutation(
    validator: SQLValidator,
) -> None:
    rng = random.Random(SEED)
    for iteration in range(ITERATIONS):
        original = rng.choice(KNOWN_BAD)
        mutated = _mutate(original, rng)
        result = validator.validate(mutated)
        assert not result.valid, (
            f"seed={SEED} iteration={iteration}: {original!r} became valid as {mutated!r}"
        )


def test_known_good_statements_stay_valid_under_semantics_preserving_mutation(
    validator: SQLValidator,
) -> None:
    rng = random.Random(SEED + 1)
    for iteration in range(ITERATIONS):
        original = rng.choice(KNOWN_GOOD)
        mutated = _mutate(original, rng)
        result = validator.validate(mutated)
        assert result.valid, (
            f"seed={SEED + 1} iteration={iteration}: {original!r} was rejected as {mutated!r}: "
            f"{result.errors}"
        )


def test_random_token_soup_never_crashes_and_acceptance_is_always_safe(
    validator: SQLValidator,
) -> None:
    rng = random.Random(SEED + 2)
    for iteration in range(ITERATIONS * 4):
        length = rng.randint(1, 30)
        sql = " ".join(rng.choice(TOKEN_POOL) for _ in range(length))
        _assert_safe_acceptance(validator, sql, f"seed={SEED + 2} iteration={iteration}")


@pytest.mark.parametrize(
    "hostile",
    [
        "",
        " ",
        "\x00",
        "SELECT '",
        "SELECT \"",
        "SELECT /* unterminated",
        "SELECT " + "(" * 500 + "1" + ")" * 500,
        "SELECT " + "1 + " * 2000 + "1",
        "SELECT " + "a" * 50_000,
        "SELECT $$ unterminated",
        "SELECT 'é🚗' FROM vehicles",
        "\n\n\n;;;\n",
        "SELECT 1 FROM " + ", ".join(["vehicles"] * 200),
    ],
)
def test_hostile_inputs_are_rejected_or_safely_accepted_never_crash(
    validator: SQLValidator, hostile: str
) -> None:
    _assert_safe_acceptance(validator, hostile, "hostile")


def test_every_accepted_query_carries_the_row_cap() -> None:
    validator = SQLValidator(max_result_rows=50)
    rng = random.Random(SEED + 3)
    for iteration in range(ITERATIONS):
        result = validator.validate(_mutate(rng.choice(KNOWN_GOOD), rng))
        assert result.valid
        # sqlglot keeps comments, so drop them before looking for the outer LIMIT.
        sql = re.sub(r"/\*.*?\*/", "", result.normalized_sql, flags=re.DOTALL)
        limits = re.findall(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
        assert limits, f"iteration {iteration}: no LIMIT in {result.normalized_sql!r}"
        assert int(limits[-1]) <= 51, f"iteration {iteration}: {result.normalized_sql!r}"
