"""Dry-run summary of a project."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Placeholder allowance used until a measured size exists. Not a benchmark.
ESTIMATED_BYTES_PER_COLUMN = 64


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    """Tables, row counts, and parallel groups for a project.

    ``estimated_bytes_per_row`` multiplies
    :data:`ESTIMATED_BYTES_PER_COLUMN` by the column count. That figure is
    a placeholder, not a measurement of generated data or Parquet size.

    Building a plan does not draw provider values or distribution samples.

    Args:
        project: Project name from the document.
        seed: Seed recorded on the project. ``None`` when the document
            omitted it.
        order: Table names in generation order.
        row_counts: Requested rows for each table.
        parallel_groups: Tables that do not depend on each other. Names
            inside a group stay in declaration order.
        estimated_bytes_per_row: Placeholder bytes for one row of each table.
        total_rows: Sum of the requested row counts.
    """

    project: str
    seed: Any
    order: tuple[str, ...]
    row_counts: Mapping[str, int]
    parallel_groups: tuple[tuple[str, ...], ...]
    estimated_bytes_per_row: Mapping[str, int]
    total_rows: int
