import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk import calculate_position_size


def test_basic_position_size():
    qty, stop, msg = calculate_position_size(100.0, 50.0, risk_pct=0.01, stop_pct=0.02, min_trade=1.0, max_trade=100)
    assert qty == pytest.approx(1.0)
    assert stop == pytest.approx(49.0)
    assert msg is None


def test_min_trade_threshold():
    qty, stop, msg = calculate_position_size(5.0, 50.0, risk_pct=0.01, stop_pct=0.02, min_trade=1.0)
    assert qty == 0.0
    assert stop is None
    assert msg is None


def test_respects_max_trade():
    qty, stop, msg = calculate_position_size(1000.0, 10.0, risk_pct=0.05, stop_pct=0.01, min_trade=1.0, max_trade=100)
    assert qty == pytest.approx(10.0)
    assert stop == pytest.approx(9.9)
    assert msg is None
    
def test_zero_qty_returns_none_stop():
    """Extremely high priced assets can lead to quantities rounding to zero."""
    qty, stop, msg = calculate_position_size(
        100.0,
        20_000_000.0,
        risk_pct=0.01,
        stop_pct=0.02,
        min_trade=1.0,
        max_trade=10.0,
    )
    assert qty == 0.0
    assert stop is None
    assert msg is None


def test_trade_value_drops_below_min_after_rounding():
    qty, stop, msg = calculate_position_size(
        2.001,
        542.0,
        risk_pct=0.01,
        stop_pct=0.02,
        min_trade=1.0,
        max_trade=10.0,
    )
    assert qty == 0.0
    assert stop is None
    assert msg is None
