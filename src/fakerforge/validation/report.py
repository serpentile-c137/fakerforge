"""Validation reports for generated datasets."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Violation:
    """One failed data-quality check.

    Args:
        field: Column name, or ``table.column`` in a relational dataset.
            Row-count failures use ``rows`` or ``table.rows``.
        check: Check name, such as ``type`` or ``foreign_key``.
        message: Human-readable description.
        row: Zero-based row index, when the failure is in one row.
    """

    field: str
    check: str
    message: str
    row: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of validating a generated dataset.

    Args:
        rows: Number of validated rows. A relational dataset uses the sum
            of its tables.
        violations: Failures in discovery order.
        table_rows: Per-table row counts. Empty for a single table.
    """

    rows: int
    violations: tuple[Violation, ...]
    table_rows: Mapping[str, int] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """Return ``passed`` or ``failed``."""
        if self.violations:
            return "failed"
        return "passed"

    @property
    def violation_count(self) -> int:
        """Return how many violations were found."""
        return len(self.violations)

    @property
    def by_field(self) -> dict[str, tuple[Violation, ...]]:
        """Group violations by field, in discovery order."""
        grouped: dict[str, list[Violation]] = {}
        for violation in self.violations:
            grouped.setdefault(violation.field, []).append(violation)
        return {field: tuple(items) for field, items in grouped.items()}

    def __str__(self) -> str:
        if self.status == "passed":
            return f"passed: {self.rows} rows, 0 violations"
        lines = [f"failed: {self.violation_count} violations across {self.rows} rows"]
        lines.extend(violation.message for violation in self.violations)
        return "\n".join(lines)
