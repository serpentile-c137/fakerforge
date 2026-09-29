"""Generate records by calling Faker provider methods."""

from typing import Any

from fakerforge.faker import FakerForge
from fakerforge.schema.schema import Schema


class Generator:
    """Build records from a :class:`~fakerforge.schema.Schema`.

    Each field calls the named provider on the supplied
    :class:`~fakerforge.FakerForge`. The generator does not reseed; pass a
    seeded forge when results must be reproducible.

    Args:
        forge: FakerForge instance used to resolve provider methods.
    """

    def __init__(self, forge: FakerForge) -> None:
        if not isinstance(forge, FakerForge):
            raise TypeError("forge must be a FakerForge instance")
        self._forge = forge

    @property
    def forge(self) -> FakerForge:
        """Return the forge used to populate records."""
        return self._forge

    def generate_one(self, schema: Schema) -> dict[str, Any]:
        """Generate a single record.

        Args:
            schema: Fields to populate.

        Returns:
            A dictionary keyed by field name.

        Raises:
            TypeError: ``schema`` is not a :class:`Schema`, or a provider
                attribute is not callable.
        """
        if not isinstance(schema, Schema):
            raise TypeError("schema must be a Schema instance")
        record: dict[str, Any] = {}
        for column in schema.fields:
            method = getattr(self._forge, column.provider)
            if not callable(method):
                raise TypeError(f"provider {column.provider!r} is not callable")
            record[column.name] = method(**dict(column.kwargs))
        return record

    def generate(self, schema: Schema, *, count: int) -> list[dict[str, Any]]:
        """Generate ``count`` records.

        Args:
            schema: Fields to populate.
            count: Number of records. Zero yields an empty list.

        Returns:
            Records in generation order.

        Raises:
            ValueError: ``count`` is not a non-negative integer.
        """
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("count must be a non-negative integer")
        return [self.generate_one(schema) for _ in range(count)]
