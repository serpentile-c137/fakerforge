"""Seeded sampling for numeric and categorical values.

``DistributionEngine`` is the API the schema generator should call. It keeps
its own random stream, seeded from the same value as ``FakerForge``, so
distribution draws stay reproducible and do not consume Faker provider draws.
"""

import hashlib
import math
import random
from collections.abc import Sequence
from importlib import import_module
from types import ModuleType
from typing import Any

# Matches ``fakerforge.faker.Seed`` without importing that module.
Seed = int | float | str | bytes | bytearray | None

MAX_REJECTION_ATTEMPTS = 1000

_NUMERIC = ("uniform", "normal", "lognormal")


class DistributionError(ValueError):
    """Raised when sampling cannot satisfy a hard bound.

    Normal and log-normal bounds are inclusive. Draws outside the bounds are
    discarded and sampled again. They are never clipped to ``min`` or ``max``.
    This error means every attempt fell outside the bounds.
    """


class DistributionEngine:
    """Sample uniform, normal, log-normal, and categorical values.

    NumPy is used when it is installed. Without NumPy, the engine samples
    with :mod:`random`. The two backends are each deterministic for a seed,
    and they do not produce the same series.

    Args:
        seed: Seed for this engine's random stream. ``None`` draws entropy
            from the operating system.
        use_numpy: ``True`` requires NumPy, ``False`` uses the standard
            library, and ``None`` uses NumPy when it imports.
    """

    def __init__(
        self, seed: Seed | None = None, *, use_numpy: bool | None = None
    ) -> None:
        numpy = _import_numpy()
        if use_numpy is True and numpy is None:
            raise ImportError(
                "NumPy is required for this distribution engine. "
                "Install it with: pip install 'fakerforge[numpy]'"
            )
        self._numpy = numpy if use_numpy is not False else None
        self._py_rng = random.Random(seed)
        self._np_rng: Any = _numpy_generator(self._numpy, seed) if self._numpy else None

    @property
    def uses_numpy(self) -> bool:
        """Return whether sampling is going through NumPy."""
        return self._numpy is not None

    def reseed(self, seed: Seed | None = None) -> None:
        """Replace this engine's random stream.

        Args:
            seed: New seed. ``None`` draws entropy from the operating system.
        """
        self._py_rng.seed(seed)
        if self._numpy is not None:
            self._np_rng = _numpy_generator(self._numpy, seed)

    def number(
        self,
        *,
        distribution: str,
        mean: float | None = None,
        std: float | None = None,
        min: float | None = None,
        max: float | None = None,
    ) -> float:
        """Draw one float from a numeric distribution.

        ``min`` and ``max`` are inclusive hard bounds for normal and
        log-normal sampling. A draw outside those bounds is thrown away and
        another draw is taken, up to ``MAX_REJECTION_ATTEMPTS``. The engine
        does not clip a value to the nearest bound. If every attempt misses,
        this method raises :class:`DistributionError`.

        Uniform samples lie in the half-open interval ``[min, max)``. When
        ``min == max``, uniform returns that value.

        Log-normal ``mean`` and ``std`` are the mean and standard deviation
        of the underlying normal distribution, matching NumPy's
        ``Generator.lognormal``. Every untruncated log-normal sample is
        greater than zero. ``min`` must be ``>= 0`` and ``max`` must be
        ``> 0``.

        Args:
            distribution: ``"uniform"``, ``"normal"``, ``"lognormal"``, or
                ``"log-normal"``.
            mean: Required for normal and log-normal. Not accepted for uniform.
            std: Required for normal and log-normal, and must be ``> 0``.
                Not accepted for uniform.
            min: Lower inclusive bound. Required for uniform.
            max: Upper inclusive bound for normal and log-normal. Required
                for uniform, where the upper end is exclusive unless it
                equals ``min``.

        Returns:
            A Python ``float``.

        Raises:
            ValueError: The distribution name or parameters are invalid.
            DistributionError: Normal or log-normal rejection sampling could
                not find a value inside the bounds.
        """
        kind = _distribution_name(distribution)
        lower = _optional_float(min, "min")
        upper = _optional_float(max, "max")
        _require_ordered(lower, upper)
        if kind == "uniform":
            _reject_unused(mean, "mean", kind)
            _reject_unused(std, "std", kind)
            if lower is None or upper is None:
                raise ValueError("uniform requires min and max")
            if lower == upper:
                return lower
            return self._uniform(lower, upper)
        center = _required_float(mean, "mean")
        scale = _required_float(std, "std")
        if scale <= 0:
            raise ValueError("std must be greater than 0")
        if lower is not None and upper is not None and lower == upper:
            raise ValueError(
                f"{kind} bounds must span a range; values are not clipped to a point"
            )
        if kind == "lognormal":
            _validate_lognormal_bounds(lower, upper)
        draw = (
            self._normal_draw(center, scale)
            if kind == "normal"
            else self._lognormal_draw(center, scale)
        )
        return _draw_until_in_bounds(draw, lower, upper, kind)

    def categorical(
        self,
        values: Sequence[Any],
        weights: Sequence[float] | None = None,
    ) -> Any:
        """Draw one of ``values``.

        Omit ``weights`` for a uniform categorical distribution. Weights do
        not need to sum to 1; they are normalized. Selection follows the
        position in ``values``, so duplicate labels stay distinct.

        Args:
            values: Non-empty sequence of choices. Strings are not treated
                as sequences of characters.
            weights: Non-negative weights, one per value. At least one
                weight must be positive.

        Returns:
            The chosen element of ``values``, unchanged.

        Raises:
            ValueError: ``values`` or ``weights`` are empty, misaligned, or
                not a usable weight vector.
            TypeError: A weight is not numeric.
        """
        choices = _choices(values)
        if weights is None:
            index = self._weighted_index(len(choices), None)
        else:
            index = self._weighted_index(len(choices), _weights(weights, len(choices)))
        return choices[index]

    def _uniform(self, low: float, high: float) -> float:
        if self._np_rng is not None:
            return float(self._np_rng.uniform(low, high))
        return low + (high - low) * self._py_rng.random()

    def _normal_draw(self, mean: float, std: float) -> Any:
        if self._np_rng is not None:
            rng = self._np_rng
            return lambda: float(rng.normal(mean, std))
        rng_py = self._py_rng
        return lambda: rng_py.normalvariate(mean, std)

    def _lognormal_draw(self, mean: float, std: float) -> Any:
        if self._np_rng is not None:
            rng = self._np_rng
            return lambda: float(rng.lognormal(mean, std))
        rng_py = self._py_rng
        return lambda: rng_py.lognormvariate(mean, std)

    def _weighted_index(self, count: int, weights: list[float] | None) -> int:
        numpy = self._numpy
        if self._np_rng is not None and numpy is not None:
            probabilities = (
                None if weights is None else _numpy_probabilities(numpy, weights)
            )
            return int(self._np_rng.choice(count, p=probabilities))
        if weights is None:
            return self._py_rng.randrange(count)
        return self._py_rng.choices(range(count), weights=weights, k=1)[0]


def _draw_until_in_bounds(
    draw: Any,
    lower: float | None,
    upper: float | None,
    distribution: str,
) -> float:
    for _ in range(MAX_REJECTION_ATTEMPTS):
        value = float(draw())
        if _inside(value, lower, upper):
            return value
    raise DistributionError(
        f"{distribution} sample fell outside {_bound_label(lower, upper)} on "
        f"{MAX_REJECTION_ATTEMPTS} consecutive draws. Bounds are inclusive "
        "and out-of-range draws are discarded, not clipped."
    )


def _inside(value: float, lower: float | None, upper: float | None) -> bool:
    if lower is not None and value < lower:
        return False
    if upper is not None and value > upper:
        return False
    return True


def _bound_label(lower: float | None, upper: float | None) -> str:
    low = "-inf" if lower is None else repr(lower)
    high = "inf" if upper is None else repr(upper)
    return f"[{low}, {high}]"


def _distribution_name(distribution: str) -> str:
    if not isinstance(distribution, str):
        raise TypeError("distribution must be a string")
    name = distribution.strip().lower().replace("-", "")
    if name not in _NUMERIC:
        allowed = "uniform, normal, lognormal"
        raise ValueError(
            f"unknown distribution {distribution!r}; expected one of {allowed}"
        )
    return name


def _optional_float(value: object, label: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, label)


def _required_float(value: object, label: str) -> float:
    if value is None:
        raise ValueError(f"{label} is required")
    return _finite_float(value, label)


def _finite_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be an int or float")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _reject_unused(value: object, label: str, distribution: str) -> None:
    if value is not None:
        raise ValueError(f"{distribution} does not accept {label}")


def _require_ordered(lower: float | None, upper: float | None) -> None:
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("min must be less than or equal to max")


def _validate_lognormal_bounds(lower: float | None, upper: float | None) -> None:
    if lower is not None and lower < 0:
        raise ValueError("lognormal min must be greater than or equal to 0")
    if upper is not None and upper <= 0:
        raise ValueError("lognormal max must be greater than 0")


def _choices(values: Sequence[Any]) -> Sequence[Any]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("values must be a sequence of choices")
    if len(values) == 0:
        raise ValueError("values must not be empty")
    return values


def _weights(weights: Sequence[float], count: int) -> list[float]:
    if isinstance(weights, (str, bytes)) or not isinstance(weights, Sequence):
        raise TypeError("weights must be a sequence of numbers")
    if len(weights) != count:
        raise ValueError("weights must have the same length as values")
    parsed = [_finite_float(weight, "weight") for weight in weights]
    if any(weight < 0 for weight in parsed):
        raise ValueError("weights must be greater than or equal to 0")
    if sum(parsed) <= 0:
        raise ValueError("at least one weight must be greater than 0")
    return parsed


def _numpy_probabilities(numpy: ModuleType, weights: list[float]) -> Any:
    probabilities = numpy.asarray(weights, dtype=float)
    total = float(probabilities.sum())
    return probabilities / total


def _import_numpy() -> ModuleType | None:
    try:
        return import_module("numpy")
    except ImportError:
        return None


def _numpy_generator(numpy: ModuleType, seed: Seed | None) -> Any:
    return numpy.random.default_rng(_numpy_seed(seed))


def _numpy_seed(seed: Seed | None) -> int | None:
    if seed is None:
        return None
    digest = hashlib.sha256(repr(seed).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")
