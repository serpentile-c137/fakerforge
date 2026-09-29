"""Tests for the distribution engine and FakerForge sampling methods."""

import math

import pytest

from fakerforge import FakerForge
from fakerforge.distributions import DistributionEngine, DistributionError
from fakerforge.distributions import engine as engine_module


@pytest.fixture(params=["stdlib", "numpy"])
def backend(request: pytest.FixtureRequest) -> bool:
    if request.param == "numpy":
        pytest.importorskip("numpy")
        return True
    return False


def _engine(seed: object, use_numpy: bool) -> DistributionEngine:
    return DistributionEngine(seed, use_numpy=use_numpy)  # type: ignore[arg-type]


def test_fakerforge_examples_stay_in_range_and_match_the_seed() -> None:
    left = FakerForge(seed=42)
    right = FakerForge(seed=42)
    for _ in range(5):
        sample = left.number(distribution="normal", mean=50, std=10, min=18, max=80)
        assert type(sample) is float
        assert 18 <= sample <= 80
        assert sample == right.number(
            distribution="normal", mean=50, std=10, min=18, max=80
        )
        label = left.categorical(values=["A", "B", "C"], weights=[0.6, 0.3, 0.1])
        assert label == right.categorical(
            values=["A", "B", "C"], weights=[0.6, 0.3, 0.1]
        )
        assert label in {"A", "B", "C"}


def test_seed_instance_resets_distribution_draws() -> None:
    fake = FakerForge(seed=4)
    expected = [
        fake.number(distribution="uniform", min=0, max=1),
        fake.categorical(values=["A", "B", "C"]),
    ]
    fake.seed_instance(4)
    assert [
        fake.number(distribution="uniform", min=0, max=1),
        fake.categorical(values=["A", "B", "C"]),
    ] == expected


def test_provider_calls_do_not_advance_the_distribution_stream() -> None:
    left = FakerForge(seed=7)
    right = FakerForge(seed=7)
    right.name()
    right.credit_score()
    assert left.number(distribution="normal", mean=0, std=1) == right.number(
        distribution="normal", mean=0, std=1
    )


def _mixed_draws(engine: DistributionEngine) -> list[object]:
    return [
        engine.number(distribution="uniform", min=-2, max=2),
        engine.categorical(["red", "blue"], weights=[1, 3]),
    ]


def test_string_seeds_are_reproducible(backend: bool) -> None:
    assert _mixed_draws(_engine("batch-7", backend)) == _mixed_draws(
        _engine("batch-7", backend)
    )


def _series(engine: DistributionEngine) -> list[object]:
    return [
        engine.number(distribution="uniform", min=0, max=1),
        engine.number(distribution="normal", mean=50, std=10),
        engine.number(distribution="log-normal", mean=0, std=0.25),
        engine.categorical(["A", "B", "C"]),
        engine.categorical(["A", "B", "C"], weights=[0.6, 0.3, 0.1]),
    ]


def test_each_backend_is_deterministic(backend: bool) -> None:
    left = _engine(42, backend)
    right = _engine(42, backend)
    assert left.uses_numpy is backend
    assert _series(left) == _series(right)


def test_uniform_is_half_open_and_accepts_a_point(backend: bool) -> None:
    engine = _engine(1, backend)
    samples = [engine.number(distribution="uniform", min=0, max=1) for _ in range(30)]
    assert all(0 <= sample < 1 for sample in samples)
    assert engine.number(distribution="uniform", min=3, max=3) == 3


def test_normal_and_lognormal_honor_inclusive_bounds(backend: bool) -> None:
    engine = _engine(2, backend)
    normals = [
        engine.number(distribution="normal", mean=0, std=1, min=-0.5, max=0.5)
        for _ in range(20)
    ]
    logs = [
        engine.number(distribution="lognormal", mean=0, std=0.2, min=0.5, max=2)
        for _ in range(20)
    ]
    assert all(-0.5 <= sample <= 0.5 for sample in normals)
    assert all(0.5 <= sample <= 2 for sample in logs)


def test_unbounded_lognormal_is_positive(backend: bool) -> None:
    engine = _engine(3, backend)
    samples = [
        engine.number(distribution="lognormal", mean=0, std=1) for _ in range(20)
    ]
    assert all(sample > 0 for sample in samples)


def test_rejection_discards_out_of_range_draws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "MAX_REJECTION_ATTEMPTS", 4)
    draws = iter([100.0, -40.0, 80.0, 18.0])
    assert (
        engine_module._draw_until_in_bounds(lambda: next(draws), 18, 80, "normal")
        == 80.0
    )


def test_rejection_raises_instead_of_clipping(
    monkeypatch: pytest.MonkeyPatch, backend: bool
) -> None:
    monkeypatch.setattr(engine_module, "MAX_REJECTION_ATTEMPTS", 5)
    engine = _engine(1, backend)
    with pytest.raises(DistributionError, match="not clipped") as exc_info:
        engine.number(distribution="normal", mean=0, std=1, min=18, max=80)
    assert isinstance(exc_info.value, ValueError)


def test_impossible_lognormal_bounds_raise(backend: bool) -> None:
    engine = _engine(1, backend)
    with pytest.raises(DistributionError, match="not clipped"):
        engine.number(distribution="lognormal", mean=0, std=0.01, min=100, max=101)


def test_weighted_zero_selects_the_remaining_value(backend: bool) -> None:
    engine = _engine(1, backend)
    assert [engine.categorical(["A", "B"], weights=[0, 2]) for _ in range(5)] == [
        "B"
    ] * 5
    assert engine.categorical([{"id": 1}], weights=[1]) == {"id": 1}


def test_weights_do_not_need_to_sum_to_one(backend: bool) -> None:
    fractions = _engine(9, backend)
    multiples = _engine(9, backend)
    labels = ["A", "B", "C"]
    left = [fractions.categorical(labels, weights=[0.25, 0.25, 0.5]) for _ in range(12)]
    right = [multiples.categorical(labels, weights=[1, 1, 2]) for _ in range(12)]
    assert left == right


def test_invalid_numeric_parameters(backend: bool) -> None:
    engine = _engine(1, backend)
    with pytest.raises(ValueError, match="unknown distribution"):
        engine.number(distribution="poisson", mean=1, std=1)
    with pytest.raises(TypeError):
        engine.number(distribution=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mean is required"):
        engine.number(distribution="normal", std=1)
    with pytest.raises(ValueError, match="std must be greater"):
        engine.number(distribution="normal", mean=0, std=0)
    with pytest.raises(ValueError, match="does not accept mean"):
        engine.number(distribution="uniform", min=0, max=1, mean=0)
    with pytest.raises(ValueError, match="requires min and max"):
        engine.number(distribution="uniform", min=0)
    with pytest.raises(ValueError, match="less than or equal"):
        engine.number(distribution="uniform", min=2, max=1)
    with pytest.raises(ValueError, match="not clipped to a point"):
        engine.number(distribution="normal", mean=1, std=1, min=4, max=4)
    with pytest.raises(TypeError):
        engine.number(distribution="normal", mean=True, std=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        engine.number(distribution="normal", mean=0, std=math.nan)
    with pytest.raises(ValueError, match="lognormal min"):
        engine.number(distribution="lognormal", mean=0, std=1, min=-0.1)
    with pytest.raises(ValueError, match="lognormal max"):
        engine.number(distribution="log-normal", mean=0, std=1, max=0)


def test_invalid_categorical_parameters(backend: bool) -> None:
    engine = _engine(1, backend)
    with pytest.raises(ValueError, match="empty"):
        engine.categorical([])
    with pytest.raises(TypeError):
        engine.categorical("ABC")
    with pytest.raises(ValueError, match="same length"):
        engine.categorical(["A", "B"], weights=[1])
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        engine.categorical(["A", "B"], weights=[1, -1])
    with pytest.raises(ValueError, match="at least one weight"):
        engine.categorical(["A", "B"], weights=[0, 0])
    with pytest.raises(TypeError):
        engine.categorical(["A"], weights=["high"])  # type: ignore[list-item]


def test_numpy_can_be_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "_import_numpy", lambda: None)
    with pytest.raises(ImportError, match="fakerforge\\[numpy\\]"):
        DistributionEngine(seed=1, use_numpy=True)
    engine = DistributionEngine(seed=1, use_numpy=False)
    assert engine.uses_numpy is False
    assert engine.number(distribution="uniform", min=0, max=1) >= 0
