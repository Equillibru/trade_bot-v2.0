"""Risk management utilities."""

from __future__ import annotations

import math


def calculate_position_size(
    balance_usdt: float,
    price: float,
    risk_pct: float = 0.01,
    stop_pct: float = 0.02,
    min_trade: float = 0.10,
    max_trade: float = 10.0,
):
    """Compute position size and stop loss based on risk parameters.

    Parameters
    ----------
    balance_usdt: available capital in USDT
    price:       current asset price
    risk_pct:    fraction of balance to risk on the trade (e.g. 0.01 for 1%)
    stop_pct:    percentage distance from entry price to stop loss
    min_trade:   minimum notional size of the trade
    max_trade:   maximum notional size of the trade

    Returns
    -------
    tuple (qty, stop_loss)
        qty:       quantity of asset to buy
        stop_loss: price at which to exit the trade
    """
    if balance_usdt <= 0 or price <= 0 or stop_pct <= 0:
        return 0.0, None

    risk_amount = balance_usdt * risk_pct
    if risk_amount < min_trade:
        return 0.0, None

    stop_loss = price * (1 - stop_pct)
    qty = risk_amount / (price - stop_loss)
    trade_value = qty * price

    trade_value = min(max_trade, trade_value, balance_usdt)
    if trade_value < min_trade:
        return 0.0, None

    qty = math.floor((trade_value / price) * 1e6) / 1e6

    # After rounding the quantity to the supported precision it's possible
    # that it becomes zero even though the trade value satisfied the minimum
    # notional check above (e.g. very high priced assets). In such cases the
    # caller should treat the trade as invalid, so we also drop the stop loss
    # information by returning ``None``.
    if qty <= 0:
        return 0.0, None

    return qty, stop_loss
