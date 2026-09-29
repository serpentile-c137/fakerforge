"""Tests for schema types."""

import pytest

from fakerforge.schema import Field, Schema


def test_field_freezes_kwargs() -> None:
    column = Field("age", "random_int", {"min": 1, "max": 2})
    assert column.kwargs["min"] == 1
    with pytest.raises(TypeError):
        column.kwargs["min"] = 9  # type: ignore[index]


def test_field_rejects_empty_name_and_provider() -> None:
    with pytest.raises(ValueError):
        Field("", "name")
    with pytest.raises(ValueError):
        Field("name", "")


def test_field_rejects_non_mapping_kwargs() -> None:
    with pytest.raises(TypeError):
        Field("name", "name", kwargs=["nope"])  # type: ignore[arg-type]


def test_schema_preserves_order_and_accepts_a_list() -> None:
    schema = Schema(
        fields=[
            Field("name", "name"),
            Field("email", "email"),
        ]
    )
    assert [column.name for column in schema.fields] == ["name", "email"]


def test_schema_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        Schema(fields=(Field("email", "email"), Field("email", "company_email")))


def test_schema_rejects_non_fields() -> None:
    with pytest.raises(TypeError):
        Schema(fields=("name",))  # type: ignore[arg-type]
