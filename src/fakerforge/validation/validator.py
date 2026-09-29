"""Apply constraints to generated records."""

from collections.abc import Mapping, Sequence
from typing import Any

from fakerforge.constraints.base import Constraint


class ValidationError(ValueError):
    """Raised when a record fails one or more constraints.

    Args:
        errors: Failure messages, in field order.
    """

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class Validator:
    """Check record fields against named constraints.

    Only fields listed in ``constraints`` are checked. Extra record keys are
    ignored. A listed field that is absent is a failure.

    Args:
        constraints: Map of field name to constraints evaluated in order.
    """

    def __init__(
        self,
        constraints: Mapping[str, Sequence[Constraint]] | None = None,
    ) -> None:
        compiled: dict[str, tuple[Constraint, ...]] = {}
        for name, checks in (constraints or {}).items():
            if not isinstance(name, str) or name == "":
                raise ValueError("constraint field names must be non-empty strings")
            if isinstance(checks, (str, bytes)) or not isinstance(checks, Sequence):
                raise TypeError(f"constraints for {name!r} must be a sequence")
            stored = tuple(checks)
            if not all(isinstance(check, Constraint) for check in stored):
                raise TypeError(
                    f"constraints for {name!r} must be Constraint instances"
                )
            compiled[name] = stored
        self._constraints = compiled

    def validate(self, record: Mapping[str, Any]) -> list[str]:
        """Return failure messages for ``record``.

        Args:
            record: Mapping of field name to generated value.

        Returns:
            An empty list when every configured constraint passes.
        """
        if not isinstance(record, Mapping):
            raise TypeError("record must be a mapping")
        errors: list[str] = []
        for name, checks in self._constraints.items():
            if name not in record:
                errors.append(f"missing field {name!r}")
                continue
            value = record[name]
            for check in checks:
                if not check.check(value):
                    errors.append(check.message(name, value))
        return errors

    def enforce(self, record: Mapping[str, Any]) -> None:
        """Raise when ``record`` fails validation.

        Args:
            record: Mapping of field name to generated value.

        Raises:
            ValidationError: One or more constraints failed.
        """
        errors = self.validate(record)
        if errors:
            raise ValidationError(errors)
