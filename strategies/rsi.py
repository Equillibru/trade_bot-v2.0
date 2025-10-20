from __future__ import annotations

from typing import Dict, List, Sequence

from .base import Strategy


class RSIStrategy(Strategy):
    """Relative Strength Index based trading strategy.

    The strategy computes an RSI value for each symbol using a sliding window
    of recent prices. A buy signal is generated when the RSI drops below the
    oversold threshold. Positions are closed when either a simple profit target
    is hit or the RSI rises above the overbought threshold.
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        bad_words: Sequence[str] | None = None,
        fee_rate: float = 0.0,
        min_pnl_pct: float = 0.0,
    ) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.history: Dict[str, List[float]] = {}
        self.bad_words = [w.lower() for w in (bad_words or [])]
        self.fee_rate = fee_rate
        self.min_pnl_pct = min_pnl_pct

    # -- helpers -----------------------------------------------------------
    def _rsi(self, prices: List[float]) -> float | None:
        """Calculate RSI for the given price sequence."""
        if len(prices) < self.period + 1:
            return None

        gains = 0.0
        losses = 0.0
        for i in range(-self.period, 0):
            delta = prices[i] - prices[i - 1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta  # delta is negative

        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    # -- Strategy API ------------------------------------------------------
    def should_buy(self, symbol: str, price: float, headlines: Sequence[str]) -> bool:
        # basic news filter
        if any(bad in h.lower() for h in headlines for bad in self.bad_words):
            return False

        prices = self.history.setdefault(symbol, [])
        prices.append(price)
        rsi = self._rsi(prices)
        if rsi is None:
            return False
        return rsi < self.oversold

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

        rsi = self._rsi(prices)
        if rsi is None:
            return False
        if rsi > self.overbought:
            entry = position.get("entry")
            if entry is None:
                return False
            entry_cost = entry * (1 + self.fee_rate)
            current_value = price * (1 - self.fee_rate)
            profit = current_value - entry_cost
            pnl_pct = (profit / entry_cost) * 100
            return pnl_pct >= self.min_pnl_pct - 1e-6
        return False
