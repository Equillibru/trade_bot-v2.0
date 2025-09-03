"""Risk management utilities."""

from __future__ import annotations

import logging
import math


logger = logging.getLogger(__name__)


def calculate_position_size(
    balance_usdt: float,
    price: float,
    risk_pct: float = 0.02,
    stop_pct: float = 0.02,
    min_trade: float = 1.0,
    max_trade: float = 20.0,
    fee_rate : float = 0.0,
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
    tuple (qty, stop_loss, reason)
        qty:       quantity of asset to buy
        stop_loss: price at which to exit the trade
        reason:   debug message when qty is zero
    """
    if balance_usdt <= 0:
        msg = "Balance is zero"
        logger.debug(msg)
        return 0.0, None, msg

    if price <= 0 or stop_pct <= 0:
        msg = (
            f"invalid inputs (balance={balance_usdt}, price={price}, stop_pct={stop_pct})"
        )
        logger.debug(msg)
        return 0.0, None, None

    risk_amount = balance_usdt * risk_pct
    if risk_amount < min_trade:
        msg = (
            f"risk amount ${risk_amount:.2f} below minimum trade ${min_trade:.2f}"
        )
        logger.debug(msg)
        return 0.0, None, msg

    stop_loss = price * (1 - stop_pct)
    per_unit_risk = (price - stop_loss) + (price + stop_loss) * fee_rate
    qty = risk_amount / per_unit_risk
    trade_value = qty * price

    max_notional = min(max_trade, balance_usdt / (1 + fee_rate))
    trade_value = min(trade_value, max_notional)
    if trade_value < min_trade:
        msg = (
            f"Trade value ${trade_value:.2f} below minimum trade ${min_trade:.2f}"
        )
        logger.debug(msg)
        return 0.0, None, msg

    qty = math.floor((trade_value / price) * 1e6) / 1e6

    # Recompute the trade value using the rounded quantity. If the notional
    # now falls below the minimum threshold we reject the trade entirely.
    trade_value = qty * price
    if trade_value < min_trade or qty <= 0:
        msg = (
            f"trade value ${trade_value:.2f} below minimum after rounding"
        )
        logger.debug(msg)
        return 0.0, None, msg
    return qty, stop_loss, None
