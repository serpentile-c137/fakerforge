"""Base class for value constraints."""

from abc import ABC, abstractmethod
from typing import Any


class Constraint(ABC):
    """A predicate that accepts or rejects a single generated value.

    Subclasses implement :meth:`check`. Built-in constraint types are not
    part of this release.
    """

    @abstractmethod
    def check(self, value: Any) -> bool:
        """Return whether ``value`` satisfies this constraint.

        Args:
            value: Generated field value.

        Returns:
            ``True`` when the value is accepted.
        """

    def message(self, field: str, value: Any) -> str:
        """Describe a failed check.

        Args:
            field: Record field name.
            value: Value that failed :meth:`check`.

        Returns:
            A short failure message.
        """
        return f"{field!r} failed {type(self).__name__}: {value!r}"
