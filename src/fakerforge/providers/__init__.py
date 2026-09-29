"""Domain providers registered through Faker's BaseProvider."""

from fakerforge.providers.base import ForgeProvider
from fakerforge.providers.finance import FinanceProvider

__all__ = ["FinanceProvider", "ForgeProvider"]
