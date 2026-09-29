"""Finance provider built on Faker's BaseProvider."""

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from faker.providers import BaseProvider

_CENTS = Decimal("0.01")


class FinanceProvider(BaseProvider):
    """Synthetic finance fields.

    Methods draw from ``self.generator.random`` through Faker's provider
    helpers, so they follow the ``FakerForge`` instance seed.
    """

    def credit_score(self, min_score: int = 300, max_score: int = 850) -> int:
        """Return an integer credit score in the inclusive range.

        Args:
            min_score: Lowest accepted score.
            max_score: Highest accepted score.

        Returns:
            A score between ``min_score`` and ``max_score``.

        Raises:
            TypeError: A bound is not an integer.
            ValueError: ``min_score`` is greater than ``max_score``.
        """
        low = _require_int(min_score, "min_score")
        high = _require_int(max_score, "max_score")
        _require_ordered(low, high, "min_score", "max_score")
        return self.random_int(min=low, max=high)

    def transaction_amount(
        self,
        min_amount: int | float | Decimal = 1,
        max_amount: int | float | Decimal = 10000,
    ) -> Decimal:
        """Return a transaction amount in dollars and cents.

        Args:
            min_amount: Lowest accepted amount.
            max_amount: Highest accepted amount.

        Returns:
            A ``Decimal`` quantized to cents, inclusive of both bounds.

        Raises:
            TypeError: An amount is not an int, float, or Decimal.
            ValueError: An amount is not finite, or ``min_amount`` is greater
                than ``max_amount``.
        """
        low = _require_money(min_amount, "min_amount")
        high = _require_money(max_amount, "max_amount")
        _require_ordered(low, high, "min_amount", "max_amount")
        cents = self.random_int(min=_to_cents(low), max=_to_cents(high))
        return (Decimal(cents) / Decimal(100)).quantize(_CENTS)

    def account_number(self, length: int = 12) -> str:
        """Return a numeric account number of the requested length.

        Args:
            length: Number of digits. Leading zeros are allowed.

        Returns:
            A string of ``length`` digits.

        Raises:
            TypeError: ``length`` is not an integer.
            ValueError: ``length`` is less than 1.
        """
        size = _require_int(length, "length")
        if size < 1:
            raise ValueError("length must be a positive integer")
        return self.numerify("#" * size)


def _require_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an int")
    return value


def _require_money(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{label} must be an int, float, or Decimal")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not amount.is_finite():
        raise ValueError(f"{label} must be finite")
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _require_ordered(
    low: int | Decimal,
    high: int | Decimal,
    low_label: str,
    high_label: str,
) -> None:
    if low > high:
        raise ValueError(f"{low_label} must be less than or equal to {high_label}")


def _to_cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
