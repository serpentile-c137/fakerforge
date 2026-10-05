"""Yield generated rows in fixed-size batches.

Each batch is a new list. Earlier batches are not retained. Provider calls
stay scalar and use the same row function as ``FakerForge.generate``, so
concatenating batches matches ``generate`` for the same seed and schema.
``generate`` itself still builds the full in-memory result.
"""

from collections.abc import Iterator, Mapping
from typing import Any

from fakerforge.generation.keys import KeyPool
from fakerforge.schema.dataset import DatabaseSchema, DatasetSchema, SchemaError
from fakerforge.schema.generate import (
    _is_relational,
    _override_database_rows,
    _pools,
    _require_rows,
    _resolve_providers,
    _row,
)


class Batch:
    """One chunk of generated rows.

    Args:
        table: Table name. A single-table schema uses the empty string.
        rows: Records in this chunk. The length is ``batch_size`` except
            for the last chunk of a table.
    """

    def __init__(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.table = table
        self.rows = rows

    def __repr__(self) -> str:
        return f"Batch(table={self.table!r}, rows={len(self.rows)})"

    def __len__(self) -> int:
        return len(self.rows)


def iter_batches(
    forge: Any,
    schema: Mapping[str, Any] | DatasetSchema | DatabaseSchema,
    *,
    rows: int | Mapping[str, int] | None = None,
    batch_size: int = 1000,
) -> Iterator[Batch]:
    """Yield successive row chunks for a table or a relational schema.

    Args:
        forge: FakerForge instance whose providers and seeds are used.
        schema: A field mapping, dataset, table mapping, or database.
        rows: Row count for one table, or per-table counts. Relational
            tables can store ``rows`` on each table instead.
        batch_size: Maximum rows in each chunk. The default is 1000.

    Yields:
        Batches in generation order. Nothing is yielded when the row count
        is zero.

    Raises:
        ValueError: ``rows`` or ``batch_size`` is invalid.
        SchemaError: The schema or its providers are invalid.
        GenerationError: A unique value or foreign key cannot be filled
            without inventing a value.
    """
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size < 1
    ):
        raise ValueError("batch_size must be a positive integer")
    if isinstance(schema, DatabaseSchema):
        yield from _iter_database(forge, schema, rows, batch_size)
        return
    if not isinstance(schema, DatasetSchema) and _is_relational(schema):
        yield from _iter_database(forge, schema, rows, batch_size)
        return
    if rows is None or isinstance(rows, Mapping):
        raise ValueError("rows must be a non-negative integer")
    _require_rows(rows)
    parsed = (
        schema if isinstance(schema, DatasetSchema) else DatasetSchema.from_dict(schema)
    )
    yield from _iter_table_batches(forge, "", parsed, rows, {}, batch_size, None)


def _iter_database(
    forge: Any,
    schema: Mapping[str, Any] | DatabaseSchema,
    rows: int | Mapping[str, int] | None,
    batch_size: int,
) -> Iterator[Batch]:
    if isinstance(rows, bool) or isinstance(rows, int):
        raise SchemaError(["relational rows must be a mapping of table name to count"])
    if isinstance(schema, DatabaseSchema):
        database = _override_database_rows(schema, rows)
    else:
        database = DatabaseSchema.from_dict(schema, rows)
    pools: dict[tuple[str, str], KeyPool] = {}
    for table in database.in_generation_order():
        parent_keys = {key: pool.as_list() for key, pool in pools.items()}
        yield from _iter_table_batches(
            forge,
            table.name,
            table.dataset,
            table.rows,
            parent_keys,
            batch_size,
            pools,
        )


def _iter_table_batches(
    forge: Any,
    table_name: str,
    schema: DatasetSchema,
    rows: int,
    parent_keys: Mapping[tuple[str, str], list[Any]],
    batch_size: int,
    destination: dict[tuple[str, str], KeyPool] | None,
) -> Iterator[Batch]:
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
    batch: list[dict[str, Any]] = []
    for _ in range(rows):
        row = _row(forge, schema, methods, pools, seen, parent_keys, fk_pools)
        if destination is not None:
            _record_keys(table_name, schema, row, destination)
        batch.append(row)
        if len(batch) == batch_size:
            yield Batch(table_name, batch)
            batch = []
    if batch:
        yield Batch(table_name, batch)


def _record_keys(
    table_name: str,
    schema: DatasetSchema,
    row: Mapping[str, Any],
    destination: dict[tuple[str, str], KeyPool],
) -> None:
    for column in schema.columns:
        if not column.unique or row[column.name] is None:
            continue
        key = (table_name, column.name)
        pool = destination.get(key)
        if pool is None:
            pool = KeyPool()
            destination[key] = pool
        pool.add(row[column.name])
