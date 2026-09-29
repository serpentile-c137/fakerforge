"""Tests for record validation."""

import pytest

from fakerforge.constraints import Constraint
from fakerforge.validation import ValidationError, Validator


class NonEmpty(Constraint):
    def check(self, value: object) -> bool:
        return isinstance(value, str) and value != ""


class AtMost(Constraint):
    def __init__(self, limit: int) -> None:
        self.limit = limit

    def check(self, value: object) -> bool:
        return isinstance(value, int) and value <= self.limit


def test_validate_returns_no_errors_for_a_good_record() -> None:
    validator = Validator({"name": [NonEmpty()], "age": [AtMost(120)]})
    assert validator.validate({"name": "Ada", "age": 36, "extra": True}) == []


def test_validate_reports_failures_and_missing_fields() -> None:
    validator = Validator({"name": [NonEmpty()], "age": [AtMost(10)]})
    errors = validator.validate({"name": "", "note": "ignored"})
    assert any("name" in error for error in errors)
    assert any("age" in error for error in errors)


def test_enforce_raises_validation_error() -> None:
    validator = Validator({"name": [NonEmpty()]})
    with pytest.raises(ValidationError) as exc_info:
        validator.enforce({"name": ""})
    assert exc_info.value.errors
    assert isinstance(exc_info.value, ValueError)


def test_validator_rejects_bad_configuration() -> None:
    with pytest.raises(TypeError):
        Validator({"name": [object()]})  # type: ignore[list-item]
    with pytest.raises(ValueError):
        Validator({"": []})
