"""Schema types for synthetic records."""

from fakerforge.schema.dataset import (
    Column,
    DatabaseSchema,
    DatasetSchema,
    GenerationError,
    SchemaError,
    TableSchema,
)
from fakerforge.schema.result import DatabaseResult, DatasetResult
from fakerforge.schema.schema import Field, Schema

__all__ = [
    "Column",
    "DatabaseResult",
    "DatabaseSchema",
    "DatasetResult",
    "DatasetSchema",
    "Field",
    "GenerationError",
    "Schema",
    "SchemaError",
    "TableSchema",
]
