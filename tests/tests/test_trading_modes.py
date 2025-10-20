import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bootstrap_margin_main(monkeypatch, tmp_path, side_effect="MARGIN_BUY"):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "s")
    monkeypatch.setenv("NEWSAPI_KEY", "n")
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT"]))
    monkeypatch.setenv("TRADING_MODE", "margin")
    if side_effect is not None:
        monkeypatch.setenv("MARGIN_SIDE_EFFECT_TYPE", side_effect)
    else:
        monkeypatch.delenv("MARGIN_SIDE_EFFECT_TYPE", raising=False)
    db_file = tmp_path / "trades.db"
    monkeypatch.setenv("TRADE_DB_FILE", str(db_file))

    for mod in ["db", "main"]:
        if mod in sys.modules:
            del sys.modules[mod]

    import binance.client as bc

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.margin_orders = []

        def get_margin_account(self):
            return {"userAssets": [{"asset": "USDT", "free": "321.0"}]}

        def create_margin_order(self, **params):
            self.margin_orders.append(params)
            return {"orderId": 1, **params}

        def create_order(self, *args, **kwargs):  # pragma: no cover - safety net
            raise AssertionError("spot order API should not be used in margin mode")

    monkeypatch.setattr(bc, "Client", DummyClient)

    import db

    db.init_db()

    main = importlib.import_module("main")
    monkeypatch.setattr(main, "call_with_retries", lambda func, **kwargs: func())
    return main


def test_margin_balance_fetch(monkeypatch, tmp_path):
    main = _bootstrap_margin_main(monkeypatch, tmp_path)

    balance = main.get_usdt_balance()

    assert balance == pytest.approx(321.0)


def test_margin_order_uses_margin_api(monkeypatch, tmp_path):
    main = _bootstrap_margin_main(monkeypatch, tmp_path)

    main.LIVE_MODE = True

    result = main.place_order("BTCUSDT", "buy", 0.5)

    assert result["orderId"] == 1
    assert main.client.margin_orders, "expected margin order to be recorded"
    order = main.client.margin_orders[0]
    assert order["side"] == "BUY"
    assert order["sideEffectType"] == "MARGIN_BUY"


def test_margin_order_allows_no_side_effect(monkeypatch, tmp_path):
    main = _bootstrap_margin_main(monkeypatch, tmp_path, side_effect=None)

    main.LIVE_MODE = True

    result = main.place_order("BTCUSDT", "sell", 0.25)

    assert result["side"] == "SELL"
    order = main.client.margin_orders[0]
    assert "sideEffectType" not in order
