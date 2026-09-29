"""Tests for derived fields, dependencies, and foreign keys."""

from datetime import date

import pytest
from faker.providers import BaseProvider

from fakerforge import FakerForge
from fakerforge.schema import GenerationError, SchemaError

AS_OF = date(2030, 12, 31)


class FixedBirthday(BaseProvider):
    __provider__ = "fixed"

    def birthday(self) -> date:
        return date(2000, 1, 1)


def _completed_years(born: date) -> int:
    years = AS_OF.year - born.year
    if (AS_OF.month, AS_OF.day) < (born.month, born.day):
        years -= 1
    return years


def _rows(fake: FakerForge, schema: dict, rows: int, monkeypatch: pytest.MonkeyPatch):
    assert monkeypatch is not None
    result = fake.generate(schema=schema, rows=rows)
    assert isinstance(result.rows, list)
    return result.rows


def test_age_is_derived_from_date_of_birth(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = {
        "age": {"derived_from": "date_of_birth"},
        "date_of_birth": {"provider": "date.date_of_birth"},
    }
    rows = _rows(FakerForge(seed=42), schema, 8, monkeypatch)
    assert list(rows[0]) == ["age", "date_of_birth"]
    assert all(isinstance(row["date_of_birth"], date) for row in rows)
    assert all(row["age"] == _completed_years(row["date_of_birth"]) for row in rows)


def test_derived_values_match_across_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = {
        "date_of_birth": {"provider": "date.date_of_birth"},
        "age": {"derived_from": "date_of_birth"},
    }
    left = _rows(FakerForge(seed=9), schema, 5, monkeypatch)
    right = _rows(FakerForge(seed=9), schema, 5, monkeypatch)
    assert left == right


def test_dependent_date_is_on_or_after_its_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = {
        "end_date": {"type": "date", "depends_on": "start_date"},
        "start_date": {"type": "date"},
    }
    rows = _rows(FakerForge(seed=3), schema, 12, monkeypatch)
    assert list(rows[0]) == ["end_date", "start_date"]
    assert all(row["end_date"] >= row["start_date"] for row in rows)


def test_circular_field_dependency_is_rejected() -> None:
    schema = {
        "start_date": {"type": "date", "depends_on": "end_date"},
        "end_date": {"type": "date", "depends_on": "start_date"},
    }
    with pytest.raises(SchemaError, match="circular dependency") as exc_info:
        FakerForge(seed=1).generate(schema=schema, rows=1)
    message = "\n".join(exc_info.value.errors)
    assert "start_date" in message
    assert "end_date" in message


def test_derived_source_must_be_a_date() -> None:
    with pytest.raises(SchemaError, match="must be a date"):
        FakerForge(seed=1).generate(
            schema={
                "label": {"type": "string"},
                "age": {"derived_from": "label"},
            },
            rows=1,
        )
    with pytest.raises(GenerationError, match="is not a date"):
        FakerForge(seed=1).generate(
            schema={
                "name": {"provider": "person.name"},
                "age": {"derived_from": "name"},
            },
            rows=1,
        )


def test_unique_derived_values_are_not_duplicated() -> None:
    fake = FakerForge(seed=1, providers=[FixedBirthday])
    with pytest.raises(GenerationError, match="duplicates are not inserted"):
        fake.generate(
            schema={
                "date_of_birth": {"provider": "fixed.birthday"},
                "age": {"derived_from": "date_of_birth", "unique": True},
            },
            rows=2,
        )


def test_one_to_many_foreign_keys_stay_inside_the_parent() -> None:
    pandas = pytest.importorskip("pandas")
    schema = {
        "orders": {
            "rows": 10,
            "fields": {
                "order_id": {"type": "integer", "min": 1, "max": 10, "unique": True},
                "customer_id": {"references": "customers.customer_id"},
            },
        },
        "customers": {
            "rows": 4,
            "fields": {
                "customer_id": {"type": "integer", "min": 1, "max": 4, "unique": True},
                "name": {"provider": "person.name"},
            },
        },
    }
    left = FakerForge(seed=11).generate(schema=schema)
    right = FakerForge(seed=11).generate(schema=schema)
    assert list(left) == ["orders", "customers"]
    assert left["customers"].frame.equals(right["customers"].frame)
    assert left["orders"].frame.equals(right["orders"].frame)
    parent_ids = set(left["customers"].frame["customer_id"])
    child_ids = list(left["orders"].frame["customer_id"])
    assert len(parent_ids) == 4
    assert set(child_ids) <= parent_ids
    assert len(child_ids) == 10
    assert len(child_ids) > len(set(child_ids))
    assert isinstance(left["orders"].frame, pandas.DataFrame)


def test_unique_foreign_key_uses_each_parent_once() -> None:
    schema = {
        "customers": {
            "rows": 3,
            "fields": {
                "customer_id": {"type": "integer", "min": 1, "max": 3, "unique": True},
            },
        },
        "profiles": {
            "rows": 3,
            "fields": {
                "profile_id": {"type": "integer", "min": 1, "max": 3, "unique": True},
                "customer_id": {
                    "references": "customers.customer_id",
                    "unique": True,
                },
            },
        },
    }
    result = FakerForge(seed=2).generate(schema=schema)
    assert {row["customer_id"] for row in result["profiles"]} == {1, 2, 3}


def test_orphan_foreign_keys_are_rejected() -> None:
    schema = {
        "customers": {
            "rows": 0,
            "fields": {
                "customer_id": {"type": "integer", "min": 1, "max": 1, "unique": True},
            },
        },
        "orders": {
            "rows": 1,
            "fields": {
                "order_id": {"type": "uuid"},
                "customer_id": {"references": "customers.customer_id"},
            },
        },
    }
    with pytest.raises(GenerationError, match="refusing to invent a foreign key"):
        FakerForge(seed=1).generate(schema=schema)


def test_invalid_relationships_are_reported() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(SchemaError, match="must be unique"):
        fake.generate(
            schema={
                "customers": {
                    "rows": 2,
                    "fields": {"customer_id": {"type": "integer"}},
                },
                "orders": {
                    "rows": 2,
                    "fields": {"customer_id": {"references": "customers.customer_id"}},
                },
            }
        )
    with pytest.raises(SchemaError, match="unknown table"):
        fake.generate(
            schema={
                "orders": {
                    "rows": 1,
                    "fields": {"customer_id": {"references": "people.customer_id"}},
                }
            }
        )
    with pytest.raises(SchemaError, match="cannot reference itself"):
        fake.generate(
            schema={
                "orders": {
                    "rows": 1,
                    "fields": {
                        "order_id": {"type": "uuid", "unique": True},
                        "parent_id": {"references": "orders.order_id"},
                    },
                }
            }
        )
    with pytest.raises(SchemaError, match="circular table dependency"):
        fake.generate(
            schema={
                "customers": {
                    "rows": 1,
                    "fields": {
                        "customer_id": {"type": "uuid", "unique": True},
                        "order_id": {"references": "orders.order_id"},
                    },
                },
                "orders": {
                    "rows": 1,
                    "fields": {
                        "order_id": {"type": "uuid", "unique": True},
                        "customer_id": {"references": "customers.customer_id"},
                    },
                },
            }
        )
    with pytest.raises(SchemaError, match="cannot fill 3"):
        fake.generate(
            schema={
                "customers": {
                    "rows": 2,
                    "fields": {
                        "customer_id": {
                            "type": "integer",
                            "min": 1,
                            "max": 2,
                            "unique": True,
                        },
                    },
                },
                "profiles": {
                    "rows": 3,
                    "fields": {
                        "customer_id": {
                            "references": "customers.customer_id",
                            "unique": True,
                        },
                    },
                },
            }
        )


def test_flat_schema_rejects_references() -> None:
    with pytest.raises(SchemaError, match="relational schema"):
        FakerForge(seed=1).generate(
            schema={"customer_id": {"references": "customers.customer_id"}},
            rows=1,
        )
