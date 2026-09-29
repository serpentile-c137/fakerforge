"""Validate generated rows against a dataset schema."""

import math
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fakerforge.schema.dataset import Column, DatasetSchema
from fakerforge.validation.report import ValidationReport, Violation

_DATE_METHODS = frozenset(
    {"date", "date_between", "date_between_dates", "date_object", "date_of_birth"}
)
_EMAIL_METHODS = frozenset({"email", "safe_email", "free_email", "company_email"})
_NAME_METHODS = frozenset({"name", "first_name", "last_name"})
_TEXT_METHODS = frozenset({"pystr", "word", "sentence", "address"})


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Rows and schemas visible to a check.

    ``focus`` lists the tables to validate. Other tables are present so
    foreign keys can be resolved. A single table uses the empty string as
    its name.

    Args:
        tables: Row mappings keyed by table name.
        schemas: Parsed schemas for those tables.
        expected_rows: Row counts required for focused tables.
        focus: Table names this run should check.
    """

    tables: Mapping[str, Sequence[Mapping[str, Any]]]
    schemas: Mapping[str, DatasetSchema]
    expected_rows: Mapping[str, int]
    focus: tuple[str, ...]


class DatasetCheck(ABC):
    """One data-quality check.

    Subclass this and pass instances to ``validate(extra=...)``. Built-in
    checks cover types, bounds, nulls, uniqueness, known provider output,
    foreign keys, and row counts.
    """

    name: str

    @abstractmethod
    def run(self, context: ValidationContext) -> list[Violation]:
        """Return violations found in ``context``."""


class TypeCheck(DatasetCheck):
    """Reject values whose Python type does not match the schema."""

    name = "type"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation for each value of the wrong Python type."""
        found: list[Violation] = []
        for table in context.focus:
            for column in context.schemas[table].columns:
                if column.type_name is None:
                    continue
                for index, row in enumerate(context.tables[table]):
                    if column.name not in row or row[column.name] is None:
                        continue
                    value = row[column.name]
                    if _matches_type(column.type_name, value):
                        continue
                    found.append(
                        _cell(
                            table,
                            column.name,
                            self.name,
                            index,
                            _type_problem(column.type_name, value),
                        )
                    )
        return found


class BoundsCheck(DatasetCheck):
    """Reject numbers outside inclusive integer bounds or float bounds.

    Float bounds match generation: ``min`` is inclusive and ``max`` is
    exclusive, except when the two bounds are equal.
    """

    name = "bounds"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation for each number outside its schema bounds."""
        found: list[Violation] = []
        for table in context.focus:
            for column in context.schemas[table].columns:
                if column.minimum is None or column.maximum is None:
                    continue
                if column.type_name not in {"integer", "float"}:
                    continue
                for index, row in enumerate(context.tables[table]):
                    if column.name not in row:
                        continue
                    value = row[column.name]
                    if value is None or not _matches_type(column.type_name, value):
                        continue
                    problem = _bound_problem(column, value)
                    if problem is None:
                        continue
                    found.append(_cell(table, column.name, self.name, index, problem))
        return found


class NullableCheck(DatasetCheck):
    """Reject missing values and nulls in non-nullable fields."""

    name = "nullable"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation for each missing or illegal null value."""
        found: list[Violation] = []
        for table in context.focus:
            for column in context.schemas[table].columns:
                for index, row in enumerate(context.tables[table]):
                    if column.name not in row:
                        found.append(
                            _cell(
                                table,
                                column.name,
                                self.name,
                                index,
                                "value is missing",
                            )
                        )
                        continue
                    if row[column.name] is None and not column.nullable:
                        found.append(
                            _cell(
                                table,
                                column.name,
                                self.name,
                                index,
                                "null is not allowed",
                            )
                        )
        return found


class UniquenessCheck(DatasetCheck):
    """Reject repeated non-null values in unique fields."""

    name = "unique"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation for each repeated non-null unique value."""
        found: list[Violation] = []
        for table in context.focus:
            for column in context.schemas[table].columns:
                if not column.unique:
                    continue
                seen: dict[Any, int] = {}
                for index, row in enumerate(context.tables[table]):
                    if column.name not in row:
                        continue
                    value = row[column.name]
                    if value is None:
                        continue
                    if value in seen:
                        detail = (
                            f"duplicate value {value!r}; "
                            f"first seen at row {seen[value]}"
                        )
                        found.append(
                            _cell(table, column.name, self.name, index, detail)
                        )
                        continue
                    seen[value] = index
        return found


class ProviderCheck(DatasetCheck):
    """Check output of providers whose return shape is known."""

    name = "provider"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation when a known provider method has the wrong shape."""
        found: list[Violation] = []
        for table in context.focus:
            for column in context.schemas[table].columns:
                if column.method_name is None:
                    continue
                for index, row in enumerate(context.tables[table]):
                    if column.name not in row or row[column.name] is None:
                        continue
                    problem = _provider_problem(column.method_name, row[column.name])
                    if problem is None:
                        continue
                    found.append(_cell(table, column.name, self.name, index, problem))
        return found


class ForeignKeyCheck(DatasetCheck):
    """Reject foreign keys that do not exist in the parent column."""

    name = "foreign_key"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation for each foreign key missing from its parent."""
        found: list[Violation] = []
        for table in context.focus:
            for column in context.schemas[table].columns:
                if column.references_table is None or column.references_column is None:
                    continue
                parent_name = column.references_table
                parent_rows = context.tables.get(parent_name)
                label = _field_name(table, column.name)
                if parent_rows is None:
                    found.append(
                        Violation(
                            field=label,
                            check=self.name,
                            message=(
                                f"field {label!r}: parent table {parent_name!r} "
                                "is not available"
                            ),
                        )
                    )
                    continue
                allowed = {
                    row[column.references_column]
                    for row in parent_rows
                    if column.references_column in row
                    and row[column.references_column] is not None
                }
                target = f"{parent_name}.{column.references_column}"
                for index, row in enumerate(context.tables[table]):
                    if column.name not in row:
                        continue
                    value = row[column.name]
                    if value is None or value in allowed:
                        continue
                    found.append(
                        _cell(
                            table,
                            column.name,
                            self.name,
                            index,
                            f"value {value!r} is not in {target}",
                        )
                    )
        return found


class RowCountCheck(DatasetCheck):
    """Reject a table whose length differs from the requested row count."""

    name = "row_count"

    def run(self, context: ValidationContext) -> list[Violation]:
        """Return a violation when a focused table has the wrong length."""
        found: list[Violation] = []
        for table in context.focus:
            expected = context.expected_rows[table]
            actual = len(context.tables[table])
            if actual == expected:
                continue
            field = "rows" if table == "" else f"{table}.rows"
            message = f"field {field!r}: expected {expected} rows, found {actual}"
            found.append(Violation(field=field, check=self.name, message=message))
        return found


DEFAULT_CHECKS: tuple[DatasetCheck, ...] = (
    NullableCheck(),
    TypeCheck(),
    BoundsCheck(),
    UniquenessCheck(),
    ProviderCheck(),
    ForeignKeyCheck(),
    RowCountCheck(),
)


def validate_tables(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    schemas: Mapping[str, DatasetSchema],
    expected_rows: Mapping[str, int],
    *,
    focus: Sequence[str] | None = None,
    extra: Sequence[DatasetCheck] = (),
) -> ValidationReport:
    """Run the built-in checks and any ``extra`` checks.

    Args:
        tables: Generated rows keyed by table name.
        schemas: Schema for each table.
        expected_rows: Required length of each focused table.
        focus: Tables to check. Defaults to every table.
        extra: Additional checks run after the built-in checks.

    Returns:
        A report. An empty violation list has status ``passed``.
    """
    selected = tuple(tables) if focus is None else tuple(focus)
    context = ValidationContext(
        tables=tables,
        schemas=schemas,
        expected_rows=expected_rows,
        focus=selected,
    )
    violations: list[Violation] = []
    for check in (*DEFAULT_CHECKS, *extra):
        violations.extend(check.run(context))
    counted = sum(len(tables[name]) for name in selected)
    table_rows = {name: len(tables[name]) for name in selected if name != ""}
    return ValidationReport(
        rows=counted,
        violations=tuple(violations),
        table_rows=table_rows,
    )


def _field_name(table: str, column: str) -> str:
    if table == "":
        return column
    return f"{table}.{column}"


def _cell(table: str, column: str, check: str, row: int, problem: str) -> Violation:
    field = _field_name(table, column)
    return Violation(
        field=field,
        check=check,
        row=row,
        message=f"row {row}: field {field!r}: {problem}",
    )


def _matches_type(type_name: str, value: object) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        return isinstance(value, float) and math.isfinite(value)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "uuid":
        return _is_uuid(value)
    if type_name == "date":
        return isinstance(value, date) and not isinstance(value, datetime)
    return False


def _is_uuid(value: object) -> bool:
    if isinstance(value, uuid.UUID):
        return True
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _type_problem(type_name: str, value: object) -> str:
    if type_name == "float" and isinstance(value, float) and not math.isfinite(value):
        return f"expected a finite float, got {value!r}"
    return f"expected {type_name}, got {_kind(value)}"


def _kind(value: object) -> str:
    return type(value).__name__


def _bound_problem(column: Column, value: object) -> str | None:
    assert column.minimum is not None and column.maximum is not None
    if column.type_name == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if value < column.minimum or value > column.maximum:
            return f"value {value} is outside {column.minimum}..{column.maximum}"
        return None
    if not isinstance(value, float):
        return None
    if value < column.minimum:
        return f"value {value} is below {column.minimum}"
    if column.minimum == column.maximum:
        if value != column.minimum:
            return f"value {value} is not {column.minimum}"
        return None
    if value >= column.maximum:
        return f"value {value} is not below {column.maximum}"
    return None


def _provider_problem(method_name: str, value: object) -> str | None:
    if method_name in _EMAIL_METHODS:
        if not isinstance(value, str) or "@" not in value:
            return f"expected an email address, got {_kind(value)}"
        return None
    if method_name in _NAME_METHODS or method_name in _TEXT_METHODS:
        if not isinstance(value, str) or value == "":
            return f"expected non-empty text, got {_kind(value)}"
        return None
    if method_name in _DATE_METHODS:
        if not (isinstance(value, date) and not isinstance(value, datetime)):
            return f"expected a date, got {_kind(value)}"
        return None
    if method_name == "uuid4":
        if not _is_uuid(value):
            return f"expected a UUID, got {_kind(value)}"
        return None
    if method_name in {"pybool", "boolean"}:
        if not isinstance(value, bool):
            return f"expected a boolean, got {_kind(value)}"
        return None
    if method_name == "credit_score":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"expected an integer credit score, got {_kind(value)}"
        return None
    if method_name == "transaction_amount":
        if not isinstance(value, Decimal):
            return f"expected a Decimal amount, got {_kind(value)}"
        return None
    if method_name == "account_number":
        if not isinstance(value, str) or not value.isdigit():
            return f"expected a numeric account number, got {_kind(value)}"
        return None
    return None
