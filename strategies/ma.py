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
        bad_words: Sequence[str] | None = None,
        fee_rate: float = 0.0,
        min_pnl_pct: float = 0.0,
    ) -> None:
        self.short_window = short_window
        self.long_window = long_window
        self.history: Dict[str, List[float]] = {}
        self.bad_words = [w.lower() for w in (bad_words or [])]
        self.fee_rate = fee_rate
        self.min_pnl_pct = min_pnl_pct

    # -- helpers -----------------------------------------------------------
    def _ma(self, prices: List[float], window: int) -> float | None:
        if len(prices) < window:
            return None
        return sum(prices[-window:]) / window

    # -- history management ------------------------------------------------
    def seed_history(self, symbol: str, prices: Sequence[float]) -> None:
        """Seed initial price history for ``symbol``.

        This allows external components to preload historical data so that the
        strategy can evaluate signals on the very first run.
        """

        self.history[symbol] = list(prices)

    # -- Strategy API ------------------------------------------------------
    def should_buy(self, symbol: str, price: float, headlines: Sequence[str]) -> bool:
        # basic news filter
        if any(bad in h.lower() for h in headlines for bad in self.bad_words):
            return False

        prices = self.history.setdefault(symbol, [])
        prices.append(price)

        if len(prices) < self.long_window:
            # not enough data yet – wait for sufficient history
            return False

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

        take_profit = position.get("take_profit")
        if take_profit and price >= take_profit:
            return True

        if len(prices) < self.long_window:
            return False

        short = self._ma(prices, self.short_window)
        long = self._ma(prices, self.long_window)
        if short is None or long is None:
            return False
        if short < long:
            entry = position.get("entry")
            if entry is None:
                return False
            entry_cost = entry * (1 + self.fee_rate)
            current_value = price * (1 - self.fee_rate)
            profit = current_value - entry_cost
            pnl_pct = (profit / entry_cost) * 100
            return pnl_pct > self.min_pnl_pct
        return False
