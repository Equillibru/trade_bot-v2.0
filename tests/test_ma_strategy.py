from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.ma import MovingAverageCrossStrategy


def test_ma_sell_requires_positive_pnl():
    strat = MovingAverageCrossStrategy(short_window=2, long_window=3)
    symbol = "BTCUSDT"
    headlines: list[str] = []
    pos = {"entry": 10.0, "qty": 1.0}

    strat.should_sell(symbol, pos, 10.0, headlines)  # build history
    strat.should_sell(symbol, pos, 9.0, headlines)
    assert strat.should_sell(symbol, pos, 8.0, headlines) is False


def test_ma_sell_signal_on_cross_with_profit():
    strat = MovingAverageCrossStrategy(short_window=2, long_window=3)
    symbol = "ETHUSDT"
    headlines: list[str] = []
    pos = {"entry": 10.0, "qty": 1.0}

    strat.seed_history(symbol, [20.0, 10.0])
    assert strat.should_sell(symbol, pos, 15.0, headlines) is True
