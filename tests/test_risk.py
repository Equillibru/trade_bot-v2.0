import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk import calculate_position_size


def test_basic_position_size():
    qty, stop = calculate_position_size(100.0, 50.0, risk_pct=0.01, stop_pct=0.02, min_trade=0.1, max_trade=100)
    assert qty == pytest.approx(1.0)
    assert stop == pytest.approx(49.0)


def test_min_trade_threshold():
    qty, stop = calculate_position_size(5.0, 50.0, risk_pct=0.01, stop_pct=0.02, min_trade=0.1)
    assert qty == 0.0
    assert stop is None


def test_respects_max_trade():
    qty, stop = calculate_position_size(1000.0, 10.0, risk_pct=0.05, stop_pct=0.01, min_trade=0.1, max_trade=100)
    assert qty == pytest.approx(10.0)
    assert stop == pytest.approx(9.9)
