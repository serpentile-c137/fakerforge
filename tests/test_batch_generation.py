"""Batched generation beside the in-memory generate API."""

import pytest

from fakerforge import FakerForge
from fakerforge.generation import KeyPool
from fakerforge.schema import DatabaseResult, DatasetResult, GenerationError

_TABLE = {
    "customer_id": {"type": "uuid", "unique": True},
    "name": {"provider": "person.name"},
    "age": {"type": "integer", "min": 18, "max": 80},
    "email": {"provider": "internet.email", "unique": True},
}

_RELATIONAL = {
    "customers": {
        "rows": 4,
        "fields": {
            "customer_id": {"type": "uuid", "unique": True},
            "name": {"provider": "person.name"},
        },
    },
    "orders": {
        "rows": 7,
        "fields": {
            "order_id": {"type": "uuid", "unique": True},
            "customer_id": {"references": "customers.customer_id"},
        },
    },
}


def test_batches_match_generate_and_respect_size() -> None:
    full = FakerForge(seed=42).generate(schema=_TABLE, rows=5)
    batches = list(FakerForge(seed=42).iter_batches(_TABLE, rows=5, batch_size=2))
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert all(batch.table == "" for batch in batches)
    assert [row for batch in batches for row in batch.rows] == full.rows


def test_relational_batches_match_generate() -> None:
    full = FakerForge(seed=42).generate(schema=_RELATIONAL)
    grouped: dict[str, list[dict[str, object]]] = {}
    for batch in FakerForge(seed=42).iter_batches(_RELATIONAL, batch_size=3):
        grouped.setdefault(batch.table, []).extend(batch.rows)
    assert grouped["customers"] == full["customers"].rows
    assert grouped["orders"] == full["orders"].rows


def test_orphan_foreign_keys_are_refused() -> None:
    schema = {
        "customers": {
            "rows": 0,
            "fields": {"customer_id": {"type": "uuid", "unique": True}},
        },
        "orders": {
            "rows": 1,
            "fields": {
                "order_id": {"type": "uuid", "unique": True},
                "customer_id": {"references": "customers.customer_id"},
            },
        },
    }
    with pytest.raises(GenerationError, match="refusing to invent a foreign key"):
        list(FakerForge(seed=1).iter_batches(schema, batch_size=10))


def test_chunks_cover_a_few_thousand_rows_without_one_list() -> None:
    schema = {"value": {"type": "integer", "min": 0, "max": 1_000_000}}
    count = 0
    batches = 0
    for batch in FakerForge(seed=1).iter_batches(schema, rows=3000, batch_size=1000):
        assert len(batch) == 1000
        count += len(batch)
        batches += 1
    assert batches == 3
    assert count == 3000


def test_readme_generate_still_returns_validated_results() -> None:
    forge = FakerForge(seed=42)
    result = forge.generate(schema=_TABLE, rows=20)
    assert isinstance(result, DatasetResult)
    assert result.validate().status == "passed"
    tables = forge.generate(schema=_RELATIONAL)
    assert isinstance(tables, DatabaseResult)
    assert tables.validate().status == "passed"


def test_key_pool_refuses_to_invent_values() -> None:
    pool = KeyPool()
    with pytest.raises(KeyError, match="refusing to invent a foreign key"):
        pool.sample(0)
    pool.add("a")
    pool.add("b")
    pool.add("c")
    assert pool.take(0) == "a"
    assert pool.as_list() == ["c", "b"]


def test_batch_size_must_be_a_positive_integer() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        list(FakerForge(seed=1).iter_batches(_TABLE, rows=1, batch_size=0))
