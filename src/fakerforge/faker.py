"""Faker-compatible entry point."""

from collections.abc import Mapping, Sequence
from typing import Any

from faker import Faker
from faker.providers import BaseProvider

from fakerforge.distributions.engine import DistributionEngine
from fakerforge.providers.finance import FinanceProvider
from fakerforge.schema.dataset import DatabaseSchema, DatasetSchema
from fakerforge.schema.generate import generate_dataset
from fakerforge.schema.result import DatabaseResult, DatasetResult

# Matches ``faker.typing.SeedType`` without depending on a private module.
Seed = int | float | str | bytes | bytearray | None

# Registered on every instance. Later ``add_provider`` calls take precedence.
_BUILTIN_PROVIDERS: tuple[type[BaseProvider], ...] = (FinanceProvider,)


class FakerForge:
    """Wrapper around a :class:`faker.Faker` instance.

    Attributes and methods that FakerForge does not define are delegated to
    the underlying Faker instance. Built-in domain providers, including
    finance, are registered with ``add_provider`` and use that instance's
    random generator. Numeric and categorical distributions use a separate
    :class:`~fakerforge.distributions.DistributionEngine` seeded with the
    same value. Seeding uses ``seed_instance``, so it affects only this
    object and leaves Faker's shared random state alone.

    Args:
        locale: Locale or sequence of locales forwarded to Faker. ``None``
            selects Faker's default locale.
        seed: Seed forwarded to ``seed_instance``. ``None`` leaves this
            instance unseeded.
        providers: Extra providers registered after the built-in providers.
            Each item may be a provider class or an already constructed
            provider. A provider added here overrides a built-in method of
            the same name.
    """

    def __init__(
        self,
        locale: str | Sequence[str] | None = None,
        *,
        seed: Seed | None = None,
        providers: Sequence[type[BaseProvider] | BaseProvider] | None = None,
    ) -> None:
        if locale is None:
            self._faker = Faker()
        else:
            self._faker = Faker(locale)
        self._seed = seed
        self._distributions = DistributionEngine(seed)
        if seed is not None:
            self._faker.seed_instance(seed)
        registered: tuple[type[BaseProvider] | BaseProvider, ...] = _BUILTIN_PROVIDERS
        if providers:
            registered = (*registered, *providers)
        for provider in registered:
            self.add_provider(provider)

    @property
    def faker(self) -> Faker:
        """Return the wrapped Faker instance."""
        return self._faker

    def seed_instance(self, seed: Seed | None = None) -> None:
        """Reseed this instance only.

        This reseeds both the wrapped Faker generator and the distribution
        engine.

        Args:
            seed: Seed forwarded to ``Faker.seed_instance`` and the
                distribution engine.
        """
        self._seed = seed
        self._faker.seed_instance(seed)
        self._distributions.reseed(seed)

    @property
    def distributions(self) -> DistributionEngine:
        """Return the seeded distribution engine.

        Schema generation should sample through this object so numeric draws
        stay on the engine's random stream.
        """
        return self._distributions

    def number(
        self,
        *,
        distribution: str,
        mean: float | None = None,
        std: float | None = None,
        min: float | None = None,
        max: float | None = None,
    ) -> float:
        """Draw one float from ``distribution``.

        See :meth:`DistributionEngine.number` for parameters, inclusive
        normal and log-normal bounds, and the rejection rule. Out-of-range
        normal and log-normal draws are discarded, not clipped.

        Args:
            distribution: ``"uniform"``, ``"normal"``, ``"lognormal"``, or
                ``"log-normal"``.
            mean: Required for normal and log-normal.
            std: Required for normal and log-normal, and must be ``> 0``.
            min: Lower bound. Required for uniform.
            max: Upper bound. Required for uniform.

        Returns:
            A Python ``float``.
        """
        return self._distributions.number(
            distribution=distribution,
            mean=mean,
            std=std,
            min=min,
            max=max,
        )

    def categorical(
        self,
        values: Sequence[Any],
        weights: Sequence[float] | None = None,
    ) -> Any:
        """Draw one of ``values``, optionally with weights.

        Args:
            values: Non-empty sequence of choices.
            weights: Non-negative weights, one per value. Omit them for a
                uniform categorical draw.

        Returns:
            The chosen element of ``values``.
        """
        return self._distributions.categorical(values, weights)

    def generate(
        self,
        schema: Mapping[str, Any] | DatasetSchema | DatabaseSchema,
        *,
        rows: int | Mapping[str, int] | None = None,
    ) -> DatasetResult | DatabaseResult:
        """Generate a dataset from a declarative schema.

        The schema is validated before any row is produced. Integer ``min``
        and ``max`` are inclusive. Float fields use the half-open uniform
        interval ``[min, max)``. ``nullable`` fields are ``None`` with
        probability ``null_probability`` (default ``0.1``). Unique fields
        never repeat a non-null value; nulls may repeat. Derived fields are
        computed from an earlier field. A date that depends on a date is
        drawn on or after that date. Foreign keys are copied from parent
        rows that were already generated.

        Args:
            schema: A field mapping, a parsed dataset, or a relational
                mapping of tables.
            rows: Row count for a single table, or a mapping of table name
                to row count. Relational tables may instead set ``rows``
                on each table.

        Returns:
            A ``DatasetResult`` for one table, or a ``DatabaseResult`` whose
            keys are table names. Both expose ``validate()``. ``rows`` holds
            the records, and ``frame`` is a DataFrame when pandas is installed.

        Raises:
            ValueError: ``rows`` is missing or not a non-negative integer.
            SchemaError: The schema is invalid for this instance.
            GenerationError: A unique column or foreign key cannot be filled
                without inventing a value.
        """
        return generate_dataset(self, schema, rows=rows)

    def add_provider(self, provider: type[BaseProvider] | BaseProvider) -> None:
        """Register a Faker provider on the underlying instance.

        Args:
            provider: Provider class or instance accepted by
                ``Faker.add_provider``.
        """
        self._faker.add_provider(provider)

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attribute lookup to the wrapped Faker instance."""
        return getattr(self._faker, name)

    def __dir__(self) -> list[str]:
        """Include delegated Faker attributes in interactive completion."""
        return sorted(set(super().__dir__()) | set(dir(self._faker)))

    def __repr__(self) -> str:
        locales = getattr(self._faker, "locales", None)
        return f"FakerForge(locales={locales!r}, seed={self._seed!r})"
