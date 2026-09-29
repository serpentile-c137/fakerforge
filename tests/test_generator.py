"""Tests for schema-driven generation."""

import pytest

from fakerforge import FakerForge
from fakerforge.generator import Generator
from fakerforge.providers import ForgeProvider
from fakerforge.schema import Field, Schema


class StatusProvider(ForgeProvider):
    def status_code(self) -> str:
        return self.random_element(("new", "open", "closed"))


def test_generate_uses_provider_kwargs() -> None:
    schema = Schema(fields=(Field("age", "random_int", {"min": 10, "max": 10}),))
    rows = Generator(FakerForge(seed=1)).generate(schema, count=3)
    assert rows == [{"age": 10}, {"age": 10}, {"age": 10}]


def test_generate_is_reproducible() -> None:
    schema = Schema(
        fields=(
            Field("name", "name"),
            Field("email", "email"),
            Field("status", "status_code"),
        )
    )
    left = Generator(FakerForge(seed=8, providers=[StatusProvider]))
    right = Generator(FakerForge(seed=8, providers=[StatusProvider]))
    assert left.generate(schema, count=4) == right.generate(schema, count=4)


def test_generate_zero_rows() -> None:
    schema = Schema(fields=(Field("name", "name"),))
    assert Generator(FakerForge(seed=1)).generate(schema, count=0) == []


def test_generate_rejects_bad_count() -> None:
    generator = Generator(FakerForge())
    schema = Schema()
    with pytest.raises(ValueError):
        generator.generate(schema, count=-1)
    with pytest.raises(ValueError):
        generator.generate(schema, count=True)  # type: ignore[arg-type]


def test_generate_rejects_unknown_provider() -> None:
    schema = Schema(fields=(Field("value", "not_a_provider"),))
    with pytest.raises(AttributeError):
        Generator(FakerForge()).generate_one(schema)


def test_generator_requires_fakerforge() -> None:
    with pytest.raises(TypeError):
        Generator(object())  # type: ignore[arg-type]
