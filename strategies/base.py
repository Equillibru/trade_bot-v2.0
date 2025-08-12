from __future__ import annotations

from typing import Protocol, Sequence, Dict


class Strategy(Protocol):
    """Trading strategy interface.

    Implementations decide when to enter and exit positions.
    """

    def should_buy(self, symbol: str, price: float, headlines: Sequence[str]) -> bool:
        """Return True if a new position should be opened."""
        ...

    def should_sell(
        self,
        symbol: str,
        position: Dict[str, float],
        price: float,
        headlines: Sequence[str],
    ) -> bool:
        """Return True if an existing position should be closed."""
        ...
