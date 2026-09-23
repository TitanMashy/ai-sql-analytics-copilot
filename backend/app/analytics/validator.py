import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]


class SQLValidator:
    """Conservative placeholder validator until the parser-backed Sprint 5 layer."""

    _write_operation_pattern = re.compile(
        r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|call)\b",
        re.IGNORECASE,
    )
    _warning = (
        "Placeholder validation is conservative and will be replaced by AST validation in Sprint 5."
    )

    def validate(self, sql: str) -> ValidationResult:
        statement = sql.strip()
        errors: list[str] = []
        warnings = [self._warning]

        if not statement:
            errors.append("SQL query cannot be empty.")
            return ValidationResult(False, errors, warnings)

        without_trailing_semicolon = statement.rstrip(";").rstrip()
        if ";" in without_trailing_semicolon:
            errors.append("Multiple SQL statements are not permitted.")
        if not re.match(r"^select\b", without_trailing_semicolon, re.IGNORECASE):
            errors.append("Only SELECT statements are permitted.")
        if self._write_operation_pattern.search(without_trailing_semicolon):
            errors.append("Write and DDL operations are not permitted.")

        return ValidationResult(not errors, errors, warnings)
