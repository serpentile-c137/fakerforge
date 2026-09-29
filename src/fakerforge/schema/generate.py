"""Fill a declarative schema from a FakerForge instance."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from fakerforge.schema.dataset import (
    Column,
    DatabaseSchema,
    DatasetSchema,
    GenerationError,
    SchemaError,
    _is_date_source,
)
from fakerforge.schema.result import DatabaseResult, DatasetResult

MAX_UNIQUE_ATTEMPTS = 100
MAX_UNIQUE_POOL = 1_000_000
_DATE_START = date(1990, 1, 1)
_DATE_END = date(2030, 12, 31)


_NULL_DATE = object()


def generate_dataset(
    forge: Any,
    schema: Mapping[str, Any] | DatasetSchema | DatabaseSchema,
    *,
    rows: int | Mapping[str, int] | None = None,
) -> DatasetResult | DatabaseResult:
    """Generate rows from a table schema or a relational schema.

    Args:
        forge: FakerForge instance whose providers and seeds are used.
        schema: A field mapping, dataset, table mapping, or database.
        rows: Row count for one table, or per-table counts. Relational
            tables can store ``rows`` on each table instead.

    Returns:
        A ``DatasetResult`` for one table, or a ``DatabaseResult`` for a
        relational schema. Call ``validate()`` on the result. ``rows`` is
        the list of records, and ``frame`` is a DataFrame when pandas is
        installed.

    Raises:
        ValueError: A single-table row count is missing or invalid.
        SchemaError: The schema or its providers are invalid.
        GenerationError: A unique value or foreign key cannot be filled
            without inventing a value.
    """
    if isinstance(schema, DatabaseSchema):
        return _generate_database(forge, schema, rows)
    if not isinstance(schema, DatasetSchema) and _is_relational(schema):
        return _generate_database(forge, schema, rows)
    if rows is None or isinstance(rows, Mapping):
        raise ValueError("rows must be a non-negative integer")
    _require_rows(rows)
    if isinstance(schema, DatasetSchema):
        parsed = schema
    else:
        parsed = DatasetSchema.from_dict(schema)
    records = _generate_table(forge, parsed, rows, {})
    return DatasetResult(records, parsed, expected_rows=rows)


def _is_relational(schema: object) -> bool:
    if isinstance(schema, DatabaseSchema) or not isinstance(schema, Mapping):
        return isinstance(schema, DatabaseSchema)
    if len(schema) == 0:
        return False
    flags = [
        isinstance(value, Mapping) and "fields" in value for value in schema.values()
    ]
    if any(flags) and not all(flags):
        raise SchemaError(["schema mixes table definitions and field definitions"])
    return all(flags)


def _generate_database(
    forge: Any,
    schema: Mapping[str, Any] | DatabaseSchema,
    rows: int | Mapping[str, int] | None,
) -> DatabaseResult:
    if isinstance(rows, bool) or isinstance(rows, int):
        raise SchemaError(["relational rows must be a mapping of table name to count"])
    if isinstance(schema, DatabaseSchema):
        database = _override_database_rows(schema, rows)
    else:
        database = DatabaseSchema.from_dict(schema, rows)
    parent_keys: dict[tuple[str, str], list[Any]] = {}
    generated: dict[str, list[dict[str, Any]]] = {}
    for table in database.in_generation_order():
        records = _generate_table(forge, table.dataset, table.rows, parent_keys)
        generated[table.name] = records
        for column in table.dataset.columns:
            if column.unique:
                parent_keys[(table.name, column.name)] = [
                    row[column.name] for row in records if row[column.name] is not None
                ]
    results = {
        table.name: DatasetResult(
            generated[table.name],
            table.dataset,
            expected_rows=table.rows,
            table_name=table.name,
        )
        for table in database.tables
    }
    for result in results.values():
        result.siblings = results
    return DatabaseResult(results, database)


def _override_database_rows(
    database: DatabaseSchema,
    rows: Mapping[str, int] | None,
) -> DatabaseSchema:
    if rows is None:
        return database
    unknown = [
        name for name in rows if name not in {table.name for table in database.tables}
    ]
    if unknown:
        raise SchemaError([f"unknown table {name!r} in rows" for name in unknown])
    tables: list[Any] = []
    for table in database.tables:
        if table.name not in rows:
            tables.append(table)
            continue
        count = rows[table.name]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SchemaError(
                [f"table {table.name!r}: rows must be a non-negative integer"]
            )
        tables.append(type(table)(name=table.name, rows=count, dataset=table.dataset))
    return DatabaseSchema(
        tables=tuple(tables), generation_order=database.generation_order
    )


def _generate_table(
    forge: Any,
    schema: DatasetSchema,
    rows: int,
    parent_keys: Mapping[tuple[str, str], list[Any]],
) -> list[dict[str, Any]]:
    methods = _resolve_providers(forge, schema, rows)
    pools = _pools(schema)
    seen: dict[str, set[Any]] = {
        column.name: set() for column in schema.columns if column.unique
    }
    fk_pools = {
        column.name: list(
            parent_keys[(column.references_table, column.references_column)]
        )
        for column in schema.columns
        if column.unique
        and column.references_table is not None
        and column.references_column is not None
    }
    return [
        _row(forge, schema, methods, pools, seen, parent_keys, fk_pools)
        for _ in range(rows)
    ]


def _require_rows(rows: object) -> None:
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError("rows must be a non-negative integer")


def _resolve_providers(
    forge: Any, schema: DatasetSchema, rows: int
) -> dict[str, Callable[[], Any]]:
    errors: list[str] = []
    providers = list(forge.faker.providers)
    methods: dict[str, Callable[[], Any]] = {}
    for column in schema.columns:
        if column.provider_name is None or column.method_name is None:
            _capacity_error(column, rows, errors)
            continue
        method = _find_method(providers, column, errors)
        if method is not None:
            methods[column.name] = method
        _capacity_error(column, rows, errors)
    if errors:
        raise SchemaError(errors)
    return methods


def _find_method(
    providers: Sequence[Any],
    column: Column,
    errors: list[str],
) -> Callable[[], Any] | None:
    assert column.provider_name is not None
    matches = _matching_providers(providers, column.provider_name)
    prefix = f"field {column.name!r}"
    if not matches:
        errors.append(f"{prefix}: unknown provider {column.provider_name!r}")
        return None
    method_name = column.method_name
    assert method_name is not None
    for provider in matches:
        method = getattr(provider, method_name, None)
        if callable(method) and not method_name.startswith("_"):
            return method
    errors.append(
        f"{prefix}: provider {column.provider_name!r} has no method {method_name!r}"
    )
    return None


def _matching_providers(providers: Sequence[Any], name: str) -> list[Any]:
    exact = [provider for provider in providers if _provider_key(provider) == name]
    if exact or name != "date":
        return exact
    return [
        provider for provider in providers if _provider_key(provider) == "date_time"
    ]


def _provider_key(provider: object) -> str:
    declared = getattr(provider, "__provider__", "")
    if not isinstance(declared, str) or declared == "":
        return ""
    return declared.rsplit(".", 1)[-1]


def _capacity_error(column: Column, rows: int, errors: list[str]) -> None:
    if not column.unique or rows == 0:
        return
    if column.nullable and column.null_probability > 0:
        return
    prefix = f"field {column.name!r}"
    if column.type_name == "boolean" and rows > 2:
        errors.append(
            f"{prefix}: boolean unique field cannot fill {rows} non-null rows"
        )
    elif (
        column.type_name == "integer"
        and column.minimum is not None
        and column.maximum is not None
    ):
        span = int(column.maximum) - int(column.minimum) + 1
        if rows > span:
            errors.append(
                f"{prefix}: unique integer range has {span} values, "
                f"which cannot fill {rows} rows"
            )
    elif (
        column.type_name == "float"
        and column.minimum is not None
        and column.minimum == column.maximum
        and rows > 1
    ):
        errors.append(f"{prefix}: unique float field has only one distinct value")


def _row(
    forge: Any,
    schema: DatasetSchema,
    methods: Mapping[str, Callable[[], Any]],
    pools: dict[str, list[Any]],
    seen: dict[str, set[Any]],
    parent_keys: Mapping[tuple[str, str], list[Any]],
    fk_pools: dict[str, list[Any]],
) -> dict[str, Any]:
    generated: dict[str, Any] = {}
    for column in schema.in_generation_order():
        generated[column.name] = _value(
            forge,
            schema,
            column,
            methods,
            pools,
            seen,
            generated,
            parent_keys,
            fk_pools,
        )
    return {column.name: generated[column.name] for column in schema.columns}


def _pools(schema: DatasetSchema) -> dict[str, list[Any]]:
    pools: dict[str, list[Any]] = {}
    for column in schema.columns:
        if not column.unique:
            continue
        if column.type_name == "boolean":
            pools[column.name] = [False, True]
        elif (
            column.type_name == "integer"
            and column.minimum is not None
            and column.maximum is not None
        ):
            span = int(column.maximum) - int(column.minimum) + 1
            if span <= MAX_UNIQUE_POOL:
                pools[column.name] = list(
                    range(int(column.minimum), int(column.maximum) + 1)
                )
    return pools


def _value(
    forge: Any,
    schema: DatasetSchema,
    column: Column,
    methods: Mapping[str, Callable[[], Any]],
    pools: dict[str, list[Any]],
    seen: dict[str, set[Any]],
    record: Mapping[str, Any],
    parent_keys: Mapping[tuple[str, str], list[Any]],
    fk_pools: dict[str, list[Any]],
) -> Any:
    if column.derived_from is not None:
        return _derived(column, record, seen)
    if column.references_table is not None:
        return _foreign_key(forge, column, parent_keys, fk_pools)
    if column.nullable and column.null_probability > 0 and _is_null(forge, column):
        return None
    floor = _dependency_date(schema, column, record)
    if floor is _NULL_DATE:
        return None
    if isinstance(floor, date):
        return _remember_unique(column, _date_on_or_after(forge, column, floor), seen)
    pool = pools.get(column.name)
    if pool is not None:
        if not pool:
            raise GenerationError(
                f"field {column.name!r}: unique values are exhausted; "
                "duplicates are not inserted"
            )
        index = _uniform_index(forge, len(pool))
        value = pool[index]
        pool[index] = pool[-1]
        pool.pop()
        return value
    if not column.unique:
        return _draw(forge, column, methods)
    used = seen[column.name]
    for _ in range(MAX_UNIQUE_ATTEMPTS):
        value = _draw(forge, column, methods)
        if value not in used:
            used.add(value)
            return value
    raise GenerationError(
        f"field {column.name!r}: could not draw a unique value after "
        f"{MAX_UNIQUE_ATTEMPTS} attempts; duplicates are not inserted"
    )


def _is_null(forge: Any, column: Column) -> bool:
    return bool(forge.random.random() < column.null_probability)


def _uniform_index(forge: Any, size: int) -> int:
    if size == 1:
        return 0
    return int(forge.number(distribution="uniform", min=0, max=size))


def _derived(
    column: Column,
    record: Mapping[str, Any],
    seen: dict[str, set[Any]],
) -> Any:
    assert column.derived_from is not None
    source = record[column.derived_from]
    if source is None:
        return None
    if not isinstance(source, date):
        raise GenerationError(
            f"field {column.name!r}: derived_from {column.derived_from!r} is not a date"
        )
    return _remember_unique(column, _completed_years(source, column), seen)


def _completed_years(born: date, column: Column) -> int:
    years = _DATE_END.year - born.year
    if (_DATE_END.month, _DATE_END.day) < (born.month, born.day):
        years -= 1
    if years < 0:
        raise GenerationError(
            f"field {column.name!r}: derived age is negative because "
            f"{column.derived_from!r} is after {_DATE_END.isoformat()}"
        )
    return years


def _dependency_date(
    schema: DatasetSchema,
    column: Column,
    record: Mapping[str, Any],
) -> date | object | None:
    if column.type_name != "date" or not column.depends_on:
        return None
    by_name = {item.name: item for item in schema.columns}
    floors: list[date] = []
    for name in column.depends_on:
        source = by_name[name]
        value = record[name]
        if not _is_date_source(source) and not isinstance(value, date):
            continue
        if value is None:
            if column.nullable:
                return _NULL_DATE
            raise GenerationError(
                f"field {column.name!r}: {name!r} is null, "
                "so no later date can be generated"
            )
        if not isinstance(value, date):
            raise GenerationError(f"field {column.name!r}: {name!r} is not a date")
        floors.append(value)
    if not floors:
        return None
    return max(floors)


def _date_on_or_after(forge: Any, column: Column, start: date) -> date:
    if start > _DATE_END:
        raise GenerationError(
            f"field {column.name!r}: {start.isoformat()} is after "
            f"{_DATE_END.isoformat()}"
        )
    return forge.date_between_dates(date_start=start, date_end=_DATE_END)


def _foreign_key(
    forge: Any,
    column: Column,
    parent_keys: Mapping[tuple[str, str], list[Any]],
    fk_pools: dict[str, list[Any]],
) -> Any:
    if column.nullable and column.null_probability > 0 and _is_null(forge, column):
        return None
    assert column.references_table is not None and column.references_column is not None
    keys = parent_keys.get((column.references_table, column.references_column), [])
    pool = fk_pools.get(column.name)
    source = pool if pool is not None else keys
    target = f"{column.references_table}.{column.references_column}"
    if not source:
        raise GenerationError(
            f"field {column.name!r}: no values in {target}; "
            "refusing to invent a foreign key"
        )
    index = _uniform_index(forge, len(source))
    if pool is None:
        return keys[index]
    value = pool[index]
    pool[index] = pool[-1]
    pool.pop()
    return value


def _remember_unique(column: Column, value: Any, seen: dict[str, set[Any]]) -> Any:
    if not column.unique:
        return value
    used = seen[column.name]
    if value in used:
        raise GenerationError(
            f"field {column.name!r}: could not draw a unique value; "
            "duplicates are not inserted"
        )
    used.add(value)
    return value


def _draw(
    forge: Any,
    column: Column,
    methods: Mapping[str, Callable[[], Any]],
) -> Any:
    if column.method_name is not None:
        return methods[column.name]()
    if column.type_name == "string":
        return forge.pystr(min_chars=8, max_chars=16)
    if column.type_name == "integer":
        return _integer(forge, column)
    if column.type_name == "float":
        assert column.minimum is not None and column.maximum is not None
        return forge.number(
            distribution="uniform",
            min=column.minimum,
            max=column.maximum,
        )
    if column.type_name == "boolean":
        return forge.pybool()
    if column.type_name == "uuid":
        return forge.uuid4()
    if column.type_name == "date":
        return forge.date_between_dates(date_start=_DATE_START, date_end=_DATE_END)
    raise SchemaError(
        (f"field {column.name!r}: unsupported type {column.type_name!r}",)
    )


def _integer(forge: Any, column: Column) -> int:
    assert column.minimum is not None and column.maximum is not None
    low = int(column.minimum)
    high = int(column.maximum)
    if low == high:
        return low
    span = high - low + 1
    return low + int(forge.number(distribution="uniform", min=0, max=span))
