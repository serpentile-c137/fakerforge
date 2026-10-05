"""Declarative dataset schemas."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fakerforge.graph.dag import topological_order

TYPES = ("string", "integer", "float", "boolean", "uuid", "date")
_KEYS = frozenset(
    {
        "type",
        "provider",
        "min",
        "max",
        "nullable",
        "unique",
        "null_probability",
        "derived_from",
        "depends_on",
        "references",
    }
)
_TABLE_KEYS = frozenset({"fields", "rows"})
_DATE_METHODS = frozenset(
    {"date", "date_between", "date_between_dates", "date_object", "date_of_birth"}
)
DEFAULT_NULL_PROBABILITY = 0.1
DEFAULT_INTEGER_MIN = 0
DEFAULT_INTEGER_MAX = 100
DEFAULT_FLOAT_MIN = 0.0
DEFAULT_FLOAT_MAX = 1.0
_MAX_EXACT_INTEGER_SPAN = 2**53


class SchemaError(ValueError):
    """Raised when a dataset schema is invalid.

    Args:
        errors: Human-readable problems. Field messages are prefixed with
            the field name.
    """

    def __init__(self, errors: list[str] | tuple[str, ...]) -> None:
        if not errors:
            raise ValueError("SchemaError requires at least one message")
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


class GenerationError(RuntimeError):
    """Raised when a valid schema cannot be filled.

    Unique fields fail this way when the generator cannot find another
    unused non-null value. Duplicate values are not inserted.
    """


@dataclass(frozen=True, slots=True)
class Column:
    """One validated output column.

    Numeric ``minimum`` and ``maximum`` are inclusive for integers. Float
    samples use the half-open uniform interval from the distribution engine,
    except when the two bounds are equal.

    Args:
        name: Output column name.
        type_name: Primitive type, when this column is not a provider call.
        provider_name: Faker provider short name, such as ``"person"``.
        method_name: Provider method, such as ``"name"``.
        minimum: Inclusive lower numeric bound.
        maximum: Numeric upper bound. Exclusive for a non-degenerate float.
        nullable: When ``True``, generated values may be ``None``.
        null_probability: Chance of ``None`` on each row when nullable.
        unique: When ``True``, non-null values are not repeated. Nulls may
            repeat.
        derived_from: Field whose value determines this one. Supported
            derivation is completed years from a date.
        depends_on: Fields that must be generated first. A date that depends
            on a date is drawn on or after that date.
        references_table: Parent table for a foreign key.
        references_column: Parent column for a foreign key. It must be unique.
    """

    name: str
    type_name: str | None
    provider_name: str | None
    method_name: str | None
    minimum: int | float | None
    maximum: int | float | None
    nullable: bool
    null_probability: float
    unique: bool
    derived_from: str | None = None
    depends_on: tuple[str, ...] = ()
    references_table: str | None = None
    references_column: str | None = None

    @property
    def provider(self) -> str | None:
        """Return the ``provider.method`` reference, if this column has one."""
        if self.provider_name is None or self.method_name is None:
            return None
        return f"{self.provider_name}.{self.method_name}"


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    """Ordered columns parsed from a declarative schema mapping.

    ``generation_order`` is a topological order of ``columns``. Output columns
    stay in declaration order.

    Args:
        columns: Columns in output order.
        generation_order: Column names with dependencies generated first.
    """

    columns: tuple[Column, ...]
    generation_order: tuple[str, ...]

    def in_generation_order(self) -> tuple[Column, ...]:
        """Return columns with dependencies before the fields that use them."""
        by_name = {column.name: column for column in self.columns}
        return tuple(by_name[name] for name in self.generation_order)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "DatasetSchema":
        """Parse and validate ``document``.

        Provider names are not resolved here. Generation checks that each
        provider is registered on the ``FakerForge`` instance.

        Args:
            document: Mapping of column name to a field definition.

        Returns:
            A validated schema.

        Raises:
            TypeError: ``document`` is not a mapping.
            SchemaError: One or more field definitions are invalid.
        """
        if not isinstance(document, Mapping):
            raise TypeError("schema must be a mapping of field names to definitions")
        errors: list[str] = []
        columns: list[Column] = []
        seen: set[str] = set()
        if len(document) == 0:
            errors.append("schema must contain at least one field")
        for name, spec in document.items():
            if not isinstance(name, str) or name == "":
                errors.append("field names must be non-empty strings")
                continue
            if name in seen:
                errors.append(f"field {name!r}: duplicate field name")
            seen.add(name)
            parsed, field_errors = _parse_field(name, spec, relational=False)
            errors.extend(field_errors)
            if parsed is not None:
                columns.append(parsed)
        errors.extend(_link_errors(columns, table=None))
        order, cycle = _topological_order(
            [column.name for column in columns],
            {column.name: _dependency_names(column) for column in columns},
        )
        if cycle:
            errors.append(f"circular dependency among fields: {', '.join(cycle)}")
        if errors:
            raise SchemaError(errors)
        return cls(columns=tuple(columns), generation_order=tuple(order))


def _parse_field(
    name: str,
    spec: object,
    *,
    relational: bool,
    table: str | None = None,
) -> tuple[Column | None, list[str]]:
    prefix = _field_label(table, name)
    if not isinstance(spec, Mapping):
        return None, [f"{prefix}: definition must be a mapping"]
    errors: list[str] = []
    unknown = sorted(set(spec) - _KEYS)
    if unknown:
        errors.append(f"{prefix}: unknown keys {unknown}")
    type_name = spec.get("type")
    provider = spec.get("provider")
    derived_from = _optional_name(spec, "derived_from", prefix, errors)
    depends_on = _parse_depends_on(spec, prefix, errors)
    references = _parse_references(spec, prefix, errors, relational)
    chosen = [key for key in ("provider", "derived_from", "references") if key in spec]
    if "type" in spec and "derived_from" not in spec:
        chosen.append("type")
    if len(chosen) > 1:
        errors.append(
            f"{prefix}: specify one of type, provider, derived_from, or references"
        )
    if "derived_from" in spec and type_name not in {None, "integer"}:
        errors.append(f"{prefix}: a derived field must be an integer age")
    if not chosen and "type" not in spec and "derived_from" not in spec:
        errors.append(
            f"{prefix}: type, provider, derived_from, or references is required"
        )
    if derived_from is not None and depends_on:
        errors.append(
            f"{prefix}: derived_from already orders generation; "
            "do not also set depends_on"
        )
    if references is not None and depends_on:
        errors.append(f"{prefix}: a foreign key cannot also set depends_on")
    parsed_type = _parse_type(prefix, type_name, errors)
    if derived_from is not None and parsed_type is None and type_name is None:
        parsed_type = "integer"
    provider_name, method_name = _parse_provider(prefix, provider, errors)
    nullable = _parse_bool(spec.get("nullable", False), prefix, "nullable", errors)
    unique = _parse_bool(spec.get("unique", False), prefix, "unique", errors)
    if derived_from is not None and "null_probability" in spec:
        errors.append(f"{prefix}: null_probability is not used on derived fields")
    null_probability = _parse_null_probability(spec, prefix, nullable, errors)
    if derived_from is not None and null_probability not in {None, 0.0}:
        null_probability = 0.0
    minimum, maximum = _parse_bounds(
        spec,
        prefix,
        None if derived_from is not None or references is not None else parsed_type,
        provider is not None or derived_from is not None or references is not None,
        errors,
    )
    plain_number = derived_from is None and references is None and provider is None
    if parsed_type == "integer" and plain_number:
        minimum, maximum = _integer_bounds(prefix, minimum, maximum, errors)
    elif parsed_type == "float" and plain_number:
        minimum, maximum = _float_bounds(prefix, minimum, maximum, errors)
    reference_table, reference_column = references if references else (None, None)
    if (
        errors
        or nullable is None
        or unique is None
        or null_probability is None
        or depends_on is None
        or (
            parsed_type is None
            and provider_name is None
            and derived_from is None
            and reference_table is None
        )
    ):
        return None, errors
    return (
        Column(
            name=name,
            type_name=parsed_type,
            provider_name=provider_name,
            method_name=method_name,
            minimum=_numeric(minimum),
            maximum=_numeric(maximum),
            nullable=nullable,
            null_probability=null_probability,
            unique=unique,
            derived_from=derived_from,
            depends_on=tuple(depends_on),
            references_table=reference_table,
            references_column=reference_column,
        ),
        [],
    )


def _parse_type(prefix: str, type_name: object, errors: list[str]) -> str | None:
    if type_name is None:
        return None
    if not isinstance(type_name, str) or type_name not in TYPES:
        allowed = ", ".join(TYPES)
        errors.append(f"{prefix}: type must be one of {allowed}")
        return None
    return type_name


def _parse_provider(
    prefix: str,
    provider: object,
    errors: list[str],
) -> tuple[str | None, str | None]:
    if provider is None:
        return None, None
    if not isinstance(provider, str):
        errors.append(f"{prefix}: provider must be a string")
        return None, None
    parts = provider.split(".")
    if len(parts) != 2 or parts[0] == "" or parts[1] == "":
        errors.append(
            f"{prefix}: provider must look like 'person.name', got {provider!r}"
        )
        return None, None
    return parts[0], parts[1]


def _parse_bool(
    value: object, prefix: str, label: str, errors: list[str]
) -> bool | None:
    if not isinstance(value, bool):
        errors.append(f"{prefix}: {label} must be a boolean")
        return None
    return value


def _parse_null_probability(
    spec: Mapping[str, Any],
    prefix: str,
    nullable: bool | None,
    errors: list[str],
) -> float | None:
    if "null_probability" not in spec:
        if nullable:
            return DEFAULT_NULL_PROBABILITY
        return 0.0
    value = spec["null_probability"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{prefix}: null_probability must be a number from 0 to 1")
        return None
    probability = float(value)
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        errors.append(f"{prefix}: null_probability must be a number from 0 to 1")
        return None
    if nullable is False and probability != 0:
        errors.append(f"{prefix}: null_probability requires nullable to be true")
        return None
    return probability


def _parse_bounds(
    spec: Mapping[str, Any],
    prefix: str,
    type_name: str | None,
    has_provider: bool,
    errors: list[str],
) -> tuple[object, object]:
    has_min = "min" in spec
    has_max = "max" in spec
    if not has_min and not has_max:
        return None, None
    if has_provider or type_name not in {"integer", "float"}:
        errors.append(
            f"{prefix}: min and max are only valid for integer and float fields"
        )
        return None, None
    if has_min != has_max:
        errors.append(f"{prefix}: min and max must be set together")
        return None, None
    return spec.get("min"), spec.get("max")


def _integer_bounds(
    prefix: str,
    minimum: object,
    maximum: object,
    errors: list[str],
) -> tuple[int, int]:
    if minimum is None and maximum is None:
        return DEFAULT_INTEGER_MIN, DEFAULT_INTEGER_MAX
    low = _require_int(minimum, prefix, "min", errors)
    high = _require_int(maximum, prefix, "max", errors)
    if low is None or high is None:
        return DEFAULT_INTEGER_MIN, DEFAULT_INTEGER_MAX
    if low > high:
        errors.append(f"{prefix}: min must be less than or equal to max")
    elif high - low + 1 > _MAX_EXACT_INTEGER_SPAN:
        errors.append(f"{prefix}: integer range is too wide to sample uniformly")
    return low, high


def _float_bounds(
    prefix: str,
    minimum: object,
    maximum: object,
    errors: list[str],
) -> tuple[float, float]:
    if minimum is None and maximum is None:
        return DEFAULT_FLOAT_MIN, DEFAULT_FLOAT_MAX
    low = _require_float(minimum, prefix, "min", errors)
    high = _require_float(maximum, prefix, "max", errors)
    if low is None or high is None:
        return DEFAULT_FLOAT_MIN, DEFAULT_FLOAT_MAX
    if low > high:
        errors.append(f"{prefix}: min must be less than or equal to max")
    return low, high


def _require_int(
    value: object, prefix: str, label: str, errors: list[str]
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{prefix}: {label} must be an int")
        return None
    return value


def _numeric(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _field_label(table: str | None, name: str) -> str:
    if table is None:
        return f"field {name!r}"
    return f"field {table}.{name!r}"


def _optional_name(
    spec: Mapping[str, Any],
    key: str,
    prefix: str,
    errors: list[str],
) -> str | None:
    if key not in spec:
        return None
    value = spec[key]
    if not isinstance(value, str) or value == "":
        errors.append(f"{prefix}: {key} must be a field name")
        return None
    return value


def _parse_depends_on(
    spec: Mapping[str, Any],
    prefix: str,
    errors: list[str],
) -> tuple[str, ...] | None:
    if "depends_on" not in spec:
        return ()
    value = spec["depends_on"]
    if isinstance(value, str):
        names = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        names = list(value)
    else:
        errors.append(
            f"{prefix}: depends_on must be a field name or a list of field names"
        )
        return None
    if not names:
        errors.append(f"{prefix}: depends_on must name at least one field")
        return None
    parsed: list[str] = []
    for name in names:
        if not isinstance(name, str) or name == "":
            errors.append(
                f"{prefix}: depends_on must be a field name or a list of field names"
            )
            return None
        parsed.append(name)
    if len(parsed) != len(set(parsed)):
        errors.append(f"{prefix}: depends_on contains a repeated field")
        return None
    return tuple(parsed)


def _parse_references(
    spec: Mapping[str, Any],
    prefix: str,
    errors: list[str],
    relational: bool,
) -> tuple[str, str] | None:
    if "references" not in spec:
        return None
    if not relational:
        errors.append(f"{prefix}: references requires a relational schema")
        return None
    value = spec["references"]
    if not isinstance(value, str):
        errors.append(f"{prefix}: references must look like 'customers.customer_id'")
        return None
    parts = value.split(".")
    if len(parts) != 2 or parts[0] == "" or parts[1] == "":
        errors.append(
            f"{prefix}: references must look like 'customers.customer_id', "
            f"got {value!r}"
        )
        return None
    return parts[0], parts[1]


def _dependency_names(column: Column) -> tuple[str, ...]:
    names: list[str] = []
    if column.derived_from is not None:
        names.append(column.derived_from)
    names.extend(column.depends_on)
    return tuple(names)


def _is_date_source(column: Column) -> bool:
    if column.type_name == "date":
        return True
    return column.method_name in _DATE_METHODS


def _link_errors(columns: list[Column], table: str | None) -> list[str]:
    by_name = {column.name: column for column in columns}
    errors: list[str] = []
    for column in columns:
        prefix = _field_label(table, column.name)
        for dependency in _dependency_names(column):
            if dependency == column.name:
                errors.append(f"{prefix}: cannot depend on itself")
                continue
            source = by_name.get(dependency)
            if source is None:
                errors.append(f"{prefix}: unknown field {dependency!r}")
                continue
            if (
                column.derived_from == dependency
                and source.type_name not in {None, "date"}
                and not _is_date_source(source)
            ):
                errors.append(f"{prefix}: derived_from {dependency!r} must be a date")
            if (
                column.derived_from == dependency
                and source.nullable
                and not column.nullable
            ):
                errors.append(
                    f"{prefix}: must be nullable because {dependency!r} is nullable"
                )
            if (
                column.derived_from == dependency
                and not source.nullable
                and column.nullable
            ):
                errors.append(
                    f"{prefix}: cannot be nullable because "
                    f"{dependency!r} is not nullable"
                )
            if (
                column.type_name == "date"
                and dependency in column.depends_on
                and source.nullable
                and not column.nullable
            ):
                errors.append(
                    f"{prefix}: must be nullable because {dependency!r} is nullable"
                )
        if column.references_table == table and table is not None:
            errors.append(f"{prefix}: a table cannot reference itself")
    return errors


def _topological_order(
    names: list[str],
    dependencies: dict[str, tuple[str, ...]],
) -> tuple[list[str], list[str]]:
    """Return a stable order and any names left in a cycle."""
    return topological_order(names, dependencies)


@dataclass(frozen=True, slots=True)
class TableSchema:
    """One table in a relational schema.

    Args:
        name: Table name.
        rows: Number of records to generate.
        dataset: Column schema for this table.
    """

    name: str
    rows: int
    dataset: DatasetSchema


@dataclass(frozen=True, slots=True)
class DatabaseSchema:
    """Tables related by foreign keys.

    Many-to-many relationships are not represented. A child table may
    reference more than one parent, which is still one foreign key per column.

    Args:
        tables: Tables in declaration order.
        generation_order: Table names with referenced tables first.
    """

    tables: tuple[TableSchema, ...]
    generation_order: tuple[str, ...]

    def in_generation_order(self) -> tuple[TableSchema, ...]:
        """Return tables so referenced tables are generated first."""
        by_name = {table.name: table for table in self.tables}
        return tuple(by_name[name] for name in self.generation_order)

    @classmethod
    def from_dict(
        cls,
        document: Mapping[str, Any],
        rows: Mapping[str, int] | None = None,
    ) -> "DatabaseSchema":
        """Parse a mapping of table name to ``fields`` and ``rows``.

        Args:
            document: Relational schema.
            rows: Optional per-table row counts. These override ``rows``
                written on a table.

        Raises:
            TypeError: ``document`` is not a mapping.
            SchemaError: A table, field, dependency, or foreign key is invalid.
        """
        if not isinstance(document, Mapping):
            raise TypeError("schema must be a mapping of table names to definitions")
        errors: list[str] = []
        if len(document) == 0:
            errors.append("schema must contain at least one table")
        if rows is not None and not isinstance(rows, Mapping):
            errors.append("relational rows must be a mapping of table name to count")
            rows = None
        tables: list[TableSchema] = []
        for name, spec in document.items():
            if not isinstance(name, str) or name == "":
                errors.append("table names must be non-empty strings")
                continue
            table, table_errors = _parse_table(
                name, spec, None if rows is None else rows.get(name)
            )
            errors.extend(table_errors)
            if table is not None:
                tables.append(table)
        if rows is not None:
            known = {table.name for table in tables}
            for name in rows:
                if name not in known and name not in document:
                    errors.append(f"unknown table {name!r} in rows")
        errors.extend(_reference_errors(tables))
        dependencies = {
            table.name: tuple(
                sorted(
                    {
                        column.references_table
                        for column in table.dataset.columns
                        if column.references_table is not None
                    }
                )
            )
            for table in tables
        }
        order, cycle = _topological_order(
            [table.name for table in tables],
            dependencies,
        )
        if cycle:
            errors.append(f"circular table dependency: {', '.join(cycle)}")
        if errors:
            raise SchemaError(errors)
        return cls(tables=tuple(tables), generation_order=tuple(order))


def _parse_table(
    name: str,
    spec: object,
    row_override: object,
) -> tuple[TableSchema | None, list[str]]:
    errors: list[str] = []
    if not isinstance(spec, Mapping):
        return None, [f"table {name!r}: definition must be a mapping"]
    unknown = sorted(set(spec) - _TABLE_KEYS)
    if unknown:
        errors.append(f"table {name!r}: unknown keys {unknown}")
    fields = spec.get("fields")
    if not isinstance(fields, Mapping):
        errors.append(f"table {name!r}: fields must be a mapping")
        fields = {}
    row_count = row_override if row_override is not None else spec.get("rows")
    if row_override is None and "rows" not in spec:
        errors.append(f"table {name!r}: rows is required")
        parsed_rows = None
    else:
        parsed_rows = _parse_row_count(row_count, name, errors)
    columns: list[Column] = []
    seen: set[str] = set()
    if isinstance(fields, Mapping) and len(fields) == 0:
        errors.append(f"table {name!r}: must contain at least one field")
    if isinstance(fields, Mapping):
        for field_name, field_spec in fields.items():
            if not isinstance(field_name, str) or field_name == "":
                errors.append(f"table {name!r}: field names must be non-empty strings")
                continue
            if field_name in seen:
                errors.append(f"field {name}.{field_name!r}: duplicate field name")
            seen.add(field_name)
            parsed, field_errors = _parse_field(
                field_name,
                field_spec,
                relational=True,
                table=name,
            )
            errors.extend(field_errors)
            if parsed is not None:
                columns.append(parsed)
    errors.extend(_link_errors(columns, table=name))
    order, cycle = _topological_order(
        [column.name for column in columns],
        {column.name: _dependency_names(column) for column in columns},
    )
    if cycle:
        errors.append(
            f"table {name!r}: circular dependency among fields: {', '.join(cycle)}"
        )
    if errors or parsed_rows is None:
        return None, errors
    dataset = DatasetSchema(columns=tuple(columns), generation_order=tuple(order))
    return TableSchema(name=name, rows=parsed_rows, dataset=dataset), []


def _parse_row_count(value: object, table: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"table {table!r}: rows must be a non-negative integer")
        return None
    return value


def _reference_errors(tables: list[TableSchema]) -> list[str]:
    by_name = {table.name: table for table in tables}
    errors: list[str] = []
    for table in tables:
        for column in table.dataset.columns:
            if column.references_table is None or column.references_column is None:
                continue
            prefix = _field_label(table.name, column.name)
            if column.references_table == table.name:
                continue
            parent = by_name.get(column.references_table)
            if parent is None:
                errors.append(f"{prefix}: unknown table {column.references_table!r}")
                continue
            target = next(
                (
                    item
                    for item in parent.dataset.columns
                    if item.name == column.references_column
                ),
                None,
            )
            if target is None:
                errors.append(
                    f"{prefix}: unknown column "
                    f"{column.references_table}.{column.references_column!r}"
                )
                continue
            if not target.unique:
                errors.append(
                    f"{prefix}: referenced column "
                    f"{column.references_table}.{column.references_column} "
                    "must be unique"
                )
            if (
                column.unique
                and not (column.nullable and column.null_probability > 0)
                and not target.nullable
                and table.rows > parent.rows
            ):
                errors.append(
                    f"{prefix}: unique foreign key has {parent.rows} parent values, "
                    f"which cannot fill {table.rows} rows"
                )
    return errors


def _require_float(
    value: object,
    prefix: str,
    label: str,
    errors: list[str],
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{prefix}: {label} must be an int or float")
        return None
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"{prefix}: {label} must be finite")
        return None
    return number
