"""Tests for the FakerForge wrapper."""

import pytest
from faker import Faker

from fakerforge import FakerForge, __version__


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_public_methods_return_strings() -> None:
    fake = FakerForge(seed=42)
    assert isinstance(fake.name(), str)
    assert isinstance(fake.email(), str)
    assert "@" in fake.email()
    assert isinstance(fake.address(), str)


def test_same_seed_reproduces_values() -> None:
    first = FakerForge(seed=42)
    second = FakerForge(seed=42)
    assert [first.name() for _ in range(5)] == [second.name() for _ in range(5)]
    assert first.email() == second.email()
    assert first.address() == second.address()


def test_different_seeds_diverge() -> None:
    first = [FakerForge(seed=1).name() for _ in range(5)]
    second = [FakerForge(seed=2).name() for _ in range(5)]
    assert first != second


def test_seed_instance_resets_sequence() -> None:
    fake = FakerForge(seed=7)
    expected = [fake.name() for _ in range(3)]
    fake.seed_instance(7)
    assert [fake.name() for _ in range(3)] == expected


def test_unseeded_instances_are_independent() -> None:
    left = FakerForge()
    right = FakerForge(seed=99)
    right_name = right.name()
    left.name()
    assert FakerForge(seed=99).name() == right_name


def test_delegates_unknown_methods() -> None:
    fake = FakerForge(seed=1)
    assert fake.lexify("???")
    assert fake.random_int(min=4, max=4) == 4


def test_unknown_attribute_raises() -> None:
    fake = FakerForge()
    with pytest.raises(AttributeError):
        fake.not_a_real_faker_method()


def test_exposes_underlying_faker() -> None:
    fake = FakerForge(locale="en_US", seed=1)
    assert isinstance(fake.faker, Faker)
    assert "en_US" in fake.faker.locales


def test_locale_is_forwarded() -> None:
    fake = FakerForge("fr_FR", seed=1)
    assert "fr_FR" in fake.faker.locales


def test_repr_includes_seed() -> None:
    assert "seed=42" in repr(FakerForge(seed=42))
