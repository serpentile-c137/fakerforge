"""Tests for finance provider registration and values."""

from decimal import Decimal

import pytest
from faker.providers import BaseProvider

from fakerforge import FakerForge
from fakerforge.providers import FinanceProvider, ForgeProvider


class ReplacementFinance(BaseProvider):
    def credit_score(self, min_score: int = 300, max_score: int = 850) -> int:
        return 1


def test_finance_provider_uses_faker_base_provider() -> None:
    assert issubclass(FinanceProvider, BaseProvider)
    assert issubclass(ForgeProvider, BaseProvider)


def test_finance_methods_are_registered_automatically() -> None:
    fake = FakerForge(seed=42)
    providers = fake.faker.providers
    assert any(isinstance(provider, FinanceProvider) for provider in providers)
    assert isinstance(fake.credit_score(), int)
    assert isinstance(fake.transaction_amount(), Decimal)
    assert isinstance(fake.account_number(), str)


def test_later_provider_overrides_builtin_method() -> None:
    fake = FakerForge(seed=1, providers=[ReplacementFinance])
    assert fake.credit_score() == 1


def test_add_provider_still_registers_custom_methods() -> None:
    class LabelProvider(BaseProvider):
        def desk_label(self) -> str:
            return "desk"

    fake = FakerForge(seed=1)
    fake.add_provider(LabelProvider)
    assert fake.desk_label() == "desk"
    assert isinstance(fake.account_number(), str)


def test_seeded_finance_values_match() -> None:
    left = FakerForge(seed=42)
    right = FakerForge(seed=42)
    assert [left.credit_score() for _ in range(5)] == [
        right.credit_score() for _ in range(5)
    ]
    assert [left.transaction_amount() for _ in range(5)] == [
        right.transaction_amount() for _ in range(5)
    ]
    assert [left.account_number() for _ in range(5)] == [
        right.account_number() for _ in range(5)
    ]


def test_reseeding_after_construction_matches_constructor_seed() -> None:
    late = FakerForge()
    late.seed_instance(42)
    early = FakerForge(seed=42)
    assert late.credit_score() == early.credit_score()
    assert late.transaction_amount() == early.transaction_amount()
    assert late.account_number() == early.account_number()


def test_default_values_stay_inside_bounds() -> None:
    fake = FakerForge(seed=5)
    scores = [fake.credit_score() for _ in range(30)]
    amounts = [fake.transaction_amount() for _ in range(30)]
    numbers = [fake.account_number() for _ in range(10)]
    assert all(300 <= score <= 850 for score in scores)
    assert all(Decimal("1.00") <= amount <= Decimal("10000.00") for amount in amounts)
    assert all(len(number) == 12 and number.isdigit() for number in numbers)


def test_equal_bounds_return_the_bound() -> None:
    fake = FakerForge(seed=9)
    assert fake.credit_score(min_score=640, max_score=640) == 640
    assert fake.transaction_amount(
        min_amount=Decimal("12.34"), max_amount=12.34
    ) == Decimal("12.34")
    assert fake.account_number(length=1).isdigit()


def test_custom_bounds_are_inclusive() -> None:
    fake = FakerForge(seed=2)
    scores = [fake.credit_score(min_score=10, max_score=11) for _ in range(40)]
    assert set(scores) <= {10, 11}
    assert set(scores) == {10, 11}
    amounts = [
        fake.transaction_amount(min_amount=1, max_amount=1.01) for _ in range(40)
    ]
    assert set(amounts) == {Decimal("1.00"), Decimal("1.01")}


def test_invalid_credit_score_parameters() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(ValueError):
        fake.credit_score(min_score=800, max_score=300)
    with pytest.raises(TypeError):
        fake.credit_score(min_score=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        fake.credit_score(max_score=850.5)  # type: ignore[arg-type]


def test_invalid_transaction_amount_parameters() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(ValueError):
        fake.transaction_amount(min_amount=20, max_amount=10)
    with pytest.raises(TypeError):
        fake.transaction_amount(min_amount="10")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        fake.transaction_amount(max_amount=float("inf"))


def test_invalid_account_number_length() -> None:
    fake = FakerForge(seed=1)
    with pytest.raises(ValueError):
        fake.account_number(length=0)
    with pytest.raises(ValueError):
        fake.account_number(length=-3)
    with pytest.raises(TypeError):
        fake.account_number(length=12.0)  # type: ignore[arg-type]
