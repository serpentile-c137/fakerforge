"""Batched generation and foreign-key pools."""

from fakerforge.generation.batch import Batch, iter_batches
from fakerforge.generation.keys import KeyPool

__all__ = ["Batch", "KeyPool", "iter_batches"]
