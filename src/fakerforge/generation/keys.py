"""Parent unique values used to fill foreign keys.

Phase 1 stores values in a list. Callers choose the index, so this class
does not draw random numbers and does not invent a key when the pool is empty.
"""

from typing import Any


class KeyPool:
    """List-backed pool of parent key values.

    ``sample`` reads a value and leaves it in the pool. ``take`` removes it
    with swap-and-pop, matching unique foreign-key draws. An empty pool
    raises ``KeyError`` instead of returning a made-up key.
    """

    def __init__(self) -> None:
        self._values: list[Any] = []

    def add(self, value: Any) -> None:
        """Append one parent value.

        Args:
            value: Unique parent value to keep.
        """
        self._values.append(value)

    def __len__(self) -> int:
        """Return how many values are stored."""
        return len(self._values)

    def as_list(self) -> list[Any]:
        """Return the live list of values.

        The list is the pool's storage. Later ``add`` and ``take`` calls
        change it.
        """
        return self._values

    def sample(self, index: int) -> Any:
        """Return the value at ``index`` without removing it.

        Args:
            index: Position in the current list.

        Returns:
            The stored value.

        Raises:
            KeyError: The pool is empty.
            IndexError: ``index`` is outside the list.
        """
        if not self._values:
            raise KeyError("key pool is empty; refusing to invent a foreign key")
        return self._values[index]

    def take(self, index: int) -> Any:
        """Remove and return the value at ``index``.

        The last value moves into ``index`` when it is not already last.

        Args:
            index: Position to remove.

        Returns:
            The removed value.

        Raises:
            KeyError: The pool is empty.
            IndexError: ``index`` is outside the list.
        """
        if not self._values:
            raise KeyError("key pool is empty; refusing to invent a foreign key")
        value = self._values[index]
        self._values[index] = self._values[-1]
        self._values.pop()
        return value
