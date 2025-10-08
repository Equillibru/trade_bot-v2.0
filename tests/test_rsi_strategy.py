
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.rsi import RSIStrategy


def test_rsi_buy_signal_on_oversold():
    strat = RSIStrategy(period=2, oversold=30, overbought=70)
    symbol = "BTCUSDT"
    headlines: list[str] = []

    strat.should_buy(symbol, 5.0, headlines)  # build history
    strat.should_buy(symbol, 4.0, headlines)
    assert strat.should_buy(symbol, 3.0, headlines) is True


def test_rsi_sell_signal_on_overbought():
    strat = RSIStrategy(period=2, oversold=30, overbought=70)
    symbol = "ETHUSDT"
    headlines: list[str] = []
    pos = {"entry": 1.0, "qty": 1.0}

    strat.should_sell(symbol, pos, 1.0, headlines)  # build history
    strat.should_sell(symbol, pos, 2.0, headlines)
    assert strat.should_sell(symbol, pos, 3.0, headlines) is True

def test_rsi_sell_requires_positive_pnl():
    strat = RSIStrategy(period=2, oversold=30, overbought=70, fee_rate=0.1)
    symbol = "ADAUSDT"
    headlines: list[str] = []
    pos = {"entry": 1.0, "qty": 1.0}

    strat.should_sell(symbol, pos, 1.0, headlines)  # build history
    strat.should_sell(symbol, pos, 1.05, headlines)
    assert strat.should_sell(symbol, pos, 1.10, headlines) is False

def test_rsi_sell_on_profit_target_without_overbought():
    strat = RSIStrategy(
        period=2,
        oversold=30,
        overbought=70,
        fee_rate=0.1,
    )
    symbol = "XRPUSDT"
    headlines: list[str] = []
    take_profit = 1.05
    pos = {"entry": 1.0, "qty": 1.0, "take_profit": take_profit}

    strat.should_sell(symbol, pos, 1.0, headlines)  # build history
    strat.should_sell(symbol, pos, 0.99, headlines)
    assert strat.should_sell(symbol, pos, take_profit, headlines) is True
    
def test_rsi_sell_waits_for_one_percent_net_profit():
    symbol = "MATICUSDT"
    headlines: list[str] = []
    position = {"entry": 100.0, "qty": 1.0}

    strat = RSIStrategy(
        period=2,
        oversold=30,
        overbought=70,
        fee_rate=0.001,
        min_pnl_pct=1.0,
    )
    strat.should_sell(symbol, position, 100.0, headlines)
    strat.should_sell(symbol, position, 101.0, headlines)
    assert strat.should_sell(symbol, position, 101.0, headlines) is False

    strat = RSIStrategy(
        period=2,
        oversold=30,
        overbought=70,
        fee_rate=0.001,
        min_pnl_pct=1.0,
    )
    strat.should_sell(symbol, position, 100.0, headlines)
    strat.should_sell(symbol, position, 101.0, headlines)
    assert strat.should_sell(symbol, position, 102.0, headlines) is True
