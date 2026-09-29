"""Tests for the constraint base class."""

import pytest

from fakerforge.constraints import Constraint


class MinLength(Constraint):
    def __init__(self, minimum: int) -> None:
        self.minimum = minimum

    def check(self, value: object) -> bool:
        return isinstance(value, str) and len(value) >= self.minimum


def test_constraint_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Constraint()  # type: ignore[abstract]


def test_check_and_default_message() -> None:
    rule = MinLength(3)
    assert rule.check("abcd")
    assert not rule.check("ab")
    assert "name" in rule.message("name", "ab")
    assert "MinLength" in rule.message("name", "ab")
