import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk import calculate_position_size

FEE_RATE = 0.001


def test_basic_position_size():
    qty, stop, msg = calculate_position_size(
        100.0,
        50.0,
        risk_pct=0.01,
        stop_pct=0.02,
        min_trade=1.0,
        max_trade=100,
        fee_rate=FEE_RATE,
    )
    assert qty == pytest.approx(0.909918)
    assert stop == pytest.approx(49.0)
    assert msg is None


def test_zero_balance():
    qty, stop, msg = calculate_position_size(
        0.0, 50.0, risk_pct=0.01, stop_pct=0.02, min_trade=1.0, fee_rate=FEE_RATE
    )
    assert qty == 0.0
    assert stop is None
    assert msg == "Balance is zero"


def test_risk_amount_below_min_trade():
    qty, stop, msg = calculate_position_size(
        5.0, 50.0, risk_pct=0.01, stop_pct=0.02, min_trade=1.0
    )
    assert qty == 0.0
    assert stop is None
    assert msg == "risk amount $0.05 below minimum trade $1.00"

def test_trade_value_below_min_trade():
    qty, stop, msg = calculate_position_size(
        100.0,
        50.0,
        risk_pct=0.01,
        stop_pct=0.02,
        min_trade=1.0,
        max_trade=0.5,
        fee_rate=FEE_RATE,
    )
    assert qty == 0.0
    assert stop is None
    assert msg == "Trade value $0.50 below minimum trade $1.00"


def test_zero_qty_returns_message_after_rounding():
    """Extremely high priced assets can lead to quantities rounding to zero."""
    qty, stop, msg = calculate_position_size(
        100.0,
        20_000_000.0,
        risk_pct=0.01,
        stop_pct=0.02,
        min_trade=1.0,
        max_trade=10.0,
        fee_rate=FEE_RATE,
    )
    assert qty == 0.0
    assert stop is None
    assert msg == "trade value $0.00 below minimum after rounding"


def test_respects_max_trade():
    qty, stop, msg = calculate_position_size(
        1000.0,
        10.0,
        risk_pct=0.05,
        stop_pct=0.01,
        min_trade=1.0,
        max_trade=100,
        fee_rate=FEE_RATE,
    )
    assert qty == pytest.approx(10.0)
    assert stop == pytest.approx(9.9)
    assert msg is None
