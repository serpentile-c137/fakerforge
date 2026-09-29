"""Base class for sampling distributions."""

import random
from abc import ABC, abstractmethod
from typing import Any


class Distribution(ABC):
    """A reproducible sampling strategy.

    Implementations must draw randomness only from the :class:`random.Random`
    instance passed to :meth:`sample`. Built-in uniform, normal, log-normal,
    and categorical sampling lives on
    :class:`fakerforge.distributions.DistributionEngine`.
    """

    @abstractmethod
    def sample(self, rng: random.Random) -> Any:
        """Draw one value.

        Args:
            rng: Random instance owned by the caller.

        Returns:
            The sampled value.
        """
