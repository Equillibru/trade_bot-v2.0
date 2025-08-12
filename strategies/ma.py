from __future__ import annotations

from typing import Dict, List, Sequence

from .base import Strategy


class MovingAverageCrossStrategy(Strategy):
    """Simple moving‑average crossover strategy.

    The strategy maintains an in-memory price history for each symbol. It
    enters a trade when there isn't enough history yet or when the short
    moving average rises above the long moving average. Positions are closed
    when a basic profit target is hit or when the averages cross downward.
    """

    def __init__(
        self,
        short_window: int = 3,
        long_window: int = 5,
        profit_target_pct: float = 1.0,
        bad_words: Sequence[str] | None = None,
    ) -> None:
        self.short_window = short_window
        self.long_window = long_window
        self.profit_target_pct = profit_target_pct
        self.history: Dict[str, List[float]] = {}
        self.bad_words = [w.lower() for w in (bad_words or [])]

    # -- helpers -----------------------------------------------------------
    def _ma(self, prices: List[float], window: int) -> float | None:
        if len(prices) < window:
            return None
        return sum(prices[-window:]) / window

    # -- Strategy API ------------------------------------------------------
    def should_buy(self, symbol: str, price: float, headlines: Sequence[str]) -> bool:
        # basic news filter
        if any(bad in h.lower() for h in headlines for bad in self.bad_words):
            return False

        prices = self.history.setdefault(symbol, [])
        prices.append(price)

        if len(prices) < self.long_window:
            # not enough data yet – allow an initial entry
            return True

        short = self._ma(prices, self.short_window)
        long = self._ma(prices, self.long_window)
        if short is None or long is None:
            return False
        return short > long

    def should_sell(
        self,
        symbol: str,
        position: Dict[str, float],
        price: float,
        headlines: Sequence[str],
    ) -> bool:
        prices = self.history.setdefault(symbol, [])
        prices.append(price)

        entry = position.get("entry")
        if entry:
            pnl_pct = ((price - entry) / entry) * 100
            if pnl_pct >= self.profit_target_pct:  # take profits
                return True

        if len(prices) < self.long_window:
            return False

        short = self._ma(prices, self.short_window)
        long = self._ma(prices, self.long_window)
        if short is None or long is None:
            return False
        return short < long
