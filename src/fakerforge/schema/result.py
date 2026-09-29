"""Generated datasets that can be validated against their schema."""

from collections.abc import Iterator, Mapping, Sequence
from importlib import import_module
from types import ModuleType
from typing import Any

from fakerforge.schema.dataset import DatabaseSchema, DatasetSchema
from fakerforge.validation.dataset import DatasetCheck, validate_tables
from fakerforge.validation.report import ValidationReport


class DatasetResult:
    """Rows generated from one table schema.

    Args:
        rows: Generated records in schema order.
        schema: Schema those rows were generated from.
        expected_rows: Row count requested at generation time.
        table_name: Table name when this result is part of a database.
        siblings: Other tables from the same generation, used to resolve
            foreign keys.
    """

    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]],
        schema: DatasetSchema,
        *,
        expected_rows: int,
        table_name: str = "",
        siblings: Mapping[str, "DatasetResult"] | None = None,
    ) -> None:
        self.rows = [dict(row) for row in rows]
        self.schema = schema
        self.expected_rows = expected_rows
        self.table_name = table_name
        self.siblings = siblings or {}

    def __repr__(self) -> str:
        return f"DatasetResult(rows={len(self.rows)})"

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.rows[index]

    @property
    def frame(self) -> Any:
        """Return a pandas DataFrame, or ``None`` when pandas is not installed."""
        pandas = _import_pandas()
        if pandas is None:
            return None
        columns = [column.name for column in self.schema.columns]
        return pandas.DataFrame.from_records(self.rows, columns=columns)

    def validate(self, *, extra: Sequence[DatasetCheck] = ()) -> ValidationReport:
        """Validate these rows against the schema.

        Args:
            extra: Additional checks run after the built-in checks.

        Returns:
            A report with status, row count, and violations grouped by field.
        """
        tables: dict[str, Sequence[Mapping[str, Any]]] = {self.table_name: self.rows}
        schemas = {self.table_name: self.schema}
        expected = {self.table_name: self.expected_rows}
        for name, sibling in self.siblings.items():
            if name == self.table_name:
                continue
            tables[name] = sibling.rows
            schemas[name] = sibling.schema
            expected[name] = sibling.expected_rows
        return validate_tables(
            tables,
            schemas,
            expected,
            focus=(self.table_name,),
            extra=extra,
        )


class DatabaseResult:
    """Tables generated from a relational schema.

    Args:
        tables: Results in declaration order.
        schema: Relational schema used to generate them.
    """

    def __init__(
        self,
        tables: Mapping[str, DatasetResult],
        schema: DatabaseSchema,
    ) -> None:
        self.tables = dict(tables)
        self.schema = schema

    def __repr__(self) -> str:
        counts = ", ".join(
            f"{name}={len(table)}" for name, table in self.tables.items()
        )
        return f"DatabaseResult({counts})"

    def __iter__(self) -> Iterator[str]:
        return iter(self.tables)

    def __getitem__(self, name: str) -> DatasetResult:
        return self.tables[name]

    def validate(self, *, extra: Sequence[DatasetCheck] = ()) -> ValidationReport:
        """Validate every table, including foreign keys.

        Args:
            extra: Additional checks run after the built-in checks.

        Returns:
            One report covering all tables.
        """
        return validate_tables(
            {name: table.rows for name, table in self.tables.items()},
            {name: table.schema for name, table in self.tables.items()},
            {name: table.expected_rows for name, table in self.tables.items()},
            extra=extra,
        )


def _import_pandas() -> ModuleType | None:
    try:
        return import_module("pandas")
    except ImportError:
        return None
