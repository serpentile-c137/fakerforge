"""Tests for custom providers."""

from fakerforge import FakerForge
from fakerforge.providers import ForgeProvider


class BrandProvider(ForgeProvider):
    def brand_color(self) -> str:
        return self.random_element(("red", "blue", "green"))


def test_registered_provider_method_is_callable() -> None:
    fake = FakerForge(seed=3)
    fake.add_provider(BrandProvider)
    assert fake.brand_color() in {"red", "blue", "green"}


def test_provider_is_reproducible() -> None:
    left = FakerForge(seed=3, providers=[BrandProvider])
    right = FakerForge(seed=3, providers=[BrandProvider])
    assert [left.brand_color() for _ in range(4)] == [
        right.brand_color() for _ in range(4)
    ]


def test_provider_subclass_is_a_faker_provider() -> None:
    from faker.providers import BaseProvider

    assert issubclass(ForgeProvider, BaseProvider)
    assert issubclass(BrandProvider, BaseProvider)
