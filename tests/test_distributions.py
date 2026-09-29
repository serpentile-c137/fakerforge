"""Tests for the distribution base class."""

import random

import pytest

from fakerforge.distributions import Distribution


class Choice(Distribution):
    def __init__(self, options: tuple[str, ...]) -> None:
        self.options = options

    def sample(self, rng: random.Random) -> str:
        return rng.choice(self.options)


def test_distribution_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Distribution()  # type: ignore[abstract]


def test_sample_uses_caller_rng() -> None:
    distribution = Choice(("red", "blue", "green"))
    left = random.Random(11)
    right = random.Random(11)
    assert [distribution.sample(left) for _ in range(5)] == [
        distribution.sample(right) for _ in range(5)
    ]
