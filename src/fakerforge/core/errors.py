"""Errors for project documents and generation plans.

``SchemaError`` and ``GenerationError`` keep their original bases.
``isinstance`` checks against ``ValueError`` and ``RuntimeError`` stay valid.
"""


class FakerForgeError(Exception):
    """Base for project loading and planning failures."""


class PlanError(FakerForgeError):
    """Raised when a project document or dependency graph is invalid.

    Args:
        message: Human-readable failure.
        project: Project name, when it is known.
        table: Table name, when the failure is in one table.
        column: Column name, when the failure is in one column.
        dependency: Related table, column, or cycle description.
    """

    def __init__(
        self,
        message: str,
        *,
        project: str | None = None,
        table: str | None = None,
        column: str | None = None,
        dependency: str | None = None,
    ) -> None:
        self.project = project
        self.table = table
        self.column = column
        self.dependency = dependency
        super().__init__(message)
