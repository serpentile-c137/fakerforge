"""Tests for declarative schema generation."""

from datetime import date

import pytest
from faker.providers import BaseProvider

from fakerforge import FakerForge
from fakerforge.schema import DatasetSchema, GenerationError, SchemaError
from fakerforge.schema import result as result_module

CUSTOMERS = {
    "customer_id": {"type": "uuid", "unique": True},
    "name": {"provider": "person.name"},
    "age": {"type": "integer", "min": 18, "max": 80},
    "email": {"provider": "internet.email", "unique": True},
}


class SameProvider(BaseProvider):
    __provider__ = "same"

    def token(self) -> str:
        return "x"


def _rows(fake: FakerForge, schema: dict, rows: int, monkeypatch: pytest.MonkeyPatch):
    assert monkeypatch is not None
    result = fake.generate(schema=schema, rows=rows)
    assert isinstance(result.rows, list)
    return result.rows


def test_example_schema_columns_and_values(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _rows(FakerForge(seed=42), CUSTOMERS, 20, monkeypatch)
    assert [set(row) for row in rows] == [set(CUSTOMERS)] * 20
    assert len({row["customer_id"] for row in rows}) == 20
    assert len({row["email"] for row in rows}) == 20
    assert all(
        isinstance(row["customer_id"], str) and len(row["customer_id"]) == 36
        for row in rows
    )
    assert all(isinstance(row["name"], str) and row["name"] for row in rows)
    assert all(isinstance(row["age"], int) and 18 <= row["age"] <= 80 for row in rows)
    assert all("@" in row["email"] for row in rows)


def test_generate_is_reproducible() -> None:
    pandas = pytest.importorskip("pandas")
    left = FakerForge(seed=5).generate(schema=CUSTOMERS, rows=6)
    right = FakerForge(seed=5).generate(schema=CUSTOMERS, rows=6)
    assert isinstance(left.frame, pandas.DataFrame)
    assert list(left.frame.columns) == list(CUSTOMERS)
    assert left.frame.equals(right.frame)
    other = FakerForge(seed=6).generate(schema=CUSTOMERS, rows=6)
    assert not left.frame.equals(other.frame)


def test_primitive_types(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = {
        "label": {"type": "string"},
        "score": {"type": "integer", "min": 0, "max": 1},
        "ratio": {"type": "float", "min": 0, "max": 1},
        "active": {"type": "boolean"},
        "stamp": {"type": "uuid"},
        "day": {"type": "date"},
    }
    rows = _rows(FakerForge(seed=2), schema, 30, monkeypatch)
    assert all(isinstance(row["label"], str) and row["label"] for row in rows)
    assert {row["score"] for row in rows} == {0, 1}
    assert all(0 <= row["ratio"] < 1 for row in rows)
    assert all(isinstance(row["active"], bool) for row in rows)
    assert all(isinstance(row["stamp"], str) for row in rows)
    assert all(isinstance(row["day"], date) for row in rows)
    assert all(date(1990, 1, 1) <= row["day"] <= date(2030, 12, 31) for row in rows)


def test_nullable_probability(monkeypatch: pytest.MonkeyPatch) -> None:
    always = _rows(
        FakerForge(seed=1),
        {"age": {"type": "integer", "nullable": True, "null_probability": 1}},
        5,
        monkeypatch,
    )
    never = _rows(
        FakerForge(seed=1),
        {"age": {"type": "integer", "nullable": True, "null_probability": 0}},
        5,
        monkeypatch,
    )
    assert always == [{"age": None}] * 5
    assert all(row["age"] is not None for row in never)


def test_unique_integer_uses_each_value_once(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _rows(
        FakerForge(seed=3),
        {"n": {"type": "integer", "min": 0, "max": 2, "unique": True}},
        3,
        monkeypatch,
    )
    assert {row["n"] for row in rows} == {0, 1, 2}


def test_unique_nulls_may_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _rows(
        FakerForge(seed=1),
        {
            "n": {
                "type": "integer",
                "min": 0,
                "max": 0,
                "unique": True,
                "nullable": True,
                "null_probability": 1,
            }
        },
        4,
        monkeypatch,
    )
    assert rows == [{"n": None}] * 4


def test_zero_rows_keep_columns() -> None:
    pandas = pytest.importorskip("pandas")
    frame = FakerForge(seed=1).generate(schema=CUSTOMERS, rows=0).frame
    assert isinstance(frame, pandas.DataFrame)
    assert list(frame.columns) == list(CUSTOMERS)
    assert len(frame) == 0


def test_parsed_schema_can_be_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = DatasetSchema.from_dict(CUSTOMERS)
    assert parsed.columns[1].provider == "person.name"
    assert parsed.columns[2].minimum == 18
    rows = _rows(FakerForge(seed=4), parsed, 2, monkeypatch)  # type: ignore[arg-type]
    assert len(rows) == 2


def test_missing_pandas_returns_row_dicts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(result_module, "_import_pandas", lambda: None)
    result = FakerForge(seed=1).generate(schema={"active": {"type": "boolean"}}, rows=2)
    assert result.frame is None
    assert all(isinstance(row["active"], bool) for row in result.rows)


def test_schema_errors_are_collected() -> None:
    schema = {
        "age": {"type": "integer", "min": 10, "provider": "person.name"},
        "flag": {"type": "bool", "nullable": "yes"},
        "note": {"type": "string", "max": 3},
        "empty": {},
    }
    with pytest.raises(SchemaError) as exc_info:
        DatasetSchema.from_dict(schema)
    messages = "\n".join(exc_info.value.errors)
    assert "specify one of type, provider, derived_from, or references" in messages
    assert "nullable must be a boolean" in messages
    assert "type must be one of" in messages
    assert "only valid for integer and float" in messages
    assert "type, provider, derived_from, or references is required" in messages


def test_invalid_bounds_and_nulls() -> None:
    with pytest.raises(SchemaError, match="less than or equal"):
        DatasetSchema.from_dict({"age": {"type": "integer", "min": 9, "max": 1}})
    with pytest.raises(SchemaError, match="too wide"):
        DatasetSchema.from_dict({"age": {"type": "integer", "min": 0, "max": 2**53}})
    with pytest.raises(SchemaError, match="null_probability requires nullable"):
        DatasetSchema.from_dict({"age": {"type": "integer", "null_probability": 0.2}})
    with pytest.raises(SchemaError, match="0 to 1"):
        DatasetSchema.from_dict(
            {"age": {"type": "integer", "nullable": True, "null_probability": 1.5}}
        )


def test_unknown_provider_and_method() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(SchemaError, match="unknown provider") as missing:
        fake.generate(schema={"email": {"provider": "mail.email"}}, rows=3)
    assert missing.value.errors[0].startswith("field 'email'")
    with pytest.raises(SchemaError, match="has no method") as unknown:
        fake.generate(schema={"name": {"provider": "person.not_a_name"}}, rows=1)
    assert "person" in unknown.value.errors[0]


def test_unique_capacity_is_rejected_before_generation() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(SchemaError, match="boolean unique"):
        fake.generate(schema={"flag": {"type": "boolean", "unique": True}}, rows=3)
    with pytest.raises(SchemaError, match="cannot fill 4"):
        fake.generate(
            schema={"n": {"type": "integer", "min": 0, "max": 2, "unique": True}},
            rows=4,
        )


def test_unique_collision_is_not_inserted() -> None:
    fake = FakerForge(seed=1, providers=[SameProvider])
    with pytest.raises(GenerationError, match="duplicates are not inserted"):
        fake.generate(
            schema={"token": {"provider": "same.token", "unique": True}}, rows=2
        )


def test_many_to_many_key_is_rejected() -> None:
    with pytest.raises(SchemaError, match="many_to_many"):
        DatasetSchema.from_dict(
            {"orders": {"type": "integer", "many_to_many": "products"}}
        )


def test_bad_schema_shape_and_row_count() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(TypeError, match="mapping"):
        fake.generate(schema=["age"], rows=1)  # type: ignore[arg-type]
    with pytest.raises(SchemaError, match="at least one field"):
        fake.generate(schema={}, rows=1)
    with pytest.raises(SchemaError, match="definition must be a mapping"):
        fake.generate(schema={"age": "integer"}, rows=1)
    with pytest.raises(ValueError, match="rows"):
        fake.generate(schema={"age": {"type": "integer"}}, rows=-1)
    with pytest.raises(ValueError, match="rows"):
        fake.generate(schema={"age": {"type": "integer"}}, rows=True)  # type: ignore[arg-type]
