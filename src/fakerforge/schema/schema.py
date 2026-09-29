"""Declarative description of a synthetic record."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class Field:
    """One output column, produced by a Faker provider method.

    Args:
        name: Output key for the generated value.
        provider: Public method name on :class:`fakerforge.FakerForge`,
            including methods added by custom providers.
        kwargs: Keyword arguments forwarded to that method.
    """

    name: str
    provider: str
    kwargs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or self.name == "":
            raise ValueError("field name must be a non-empty string")
        if not isinstance(self.provider, str) or self.provider == "":
            raise ValueError("field provider must be a non-empty string")
        if not isinstance(self.kwargs, Mapping):
            raise TypeError("field kwargs must be a mapping")
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))


@dataclass(frozen=True, slots=True)
class Schema:
    """Ordered collection of uniquely named provider fields.

    Declarative datasets use :class:`~fakerforge.schema.dataset.DatasetSchema`
    and :meth:`fakerforge.FakerForge.generate`. Field dependencies and
    referential relationships are not represented yet.

    Args:
        fields: Fields in generation order.
    """

    fields: tuple[Field, ...] = ()

    def __post_init__(self) -> None:
        fields = self.fields
        if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
            fields = tuple(fields)
        else:
            raise TypeError("schema fields must be a sequence of Field")
        if not all(isinstance(item, Field) for item in fields):
            raise TypeError("schema fields must be Field instances")
        names = [item.name for item in fields]
        if len(names) != len(set(names)):
            raise ValueError("schema field names must be unique")
        object.__setattr__(self, "fields", fields)
