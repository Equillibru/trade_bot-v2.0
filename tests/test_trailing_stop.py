import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_trailing_stop_updates(monkeypatch, tmp_path):
    # Required environment variables for importing main
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "s")
    monkeypatch.setenv("NEWSAPI_KEY", "n")
    monkeypatch.setenv("TRADING_PAIRS", '["BTCUSDT"]')
    db_file = tmp_path / "trades.db"
    monkeypatch.setenv("TRADE_DB_FILE", str(db_file))

    # Ensure clean module imports
    for mod in ["db", "main"]:
        if mod in sys.modules:
            del sys.modules[mod]

    db = importlib.import_module("db")
    db.init_db()
    trade_id = db.log_trade("BTCUSDT", "BUY", 1.0, 100.0)
    db.upsert_position("BTCUSDT", 1.0, 100.0, 98.0, trade_id, 100.0)

    import binance.client as bc

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_asset_balance(self, asset):
            return {"free": "0"}

        def get_symbol_ticker(self, symbol):
            return {"price": "0"}

        def create_order(self, *args, **kwargs):
            return {}

        def get_account(self):
            return {"balances": []}

    monkeypatch.setattr(bc, "Client", DummyClient)

    main = importlib.import_module("main")
    monkeypatch.setattr(main, "TRADING_PAIRS", ["BTCUSDT"])
    monkeypatch.setattr(main, "load_json", lambda path, default: default)
    monkeypatch.setattr(main, "preload_history", lambda: None)
    monkeypatch.setattr(main, "get_usdt_balance", lambda: 1000.0)
    price_holder = {"price": 110.0}
    monkeypatch.setattr(main, "get_price", lambda symbol: price_holder["price"])
    monkeypatch.setattr(main, "get_news_headlines", lambda symbol: [])
    monkeypatch.setattr(
        main, "update_balance", lambda balance, positions, price_cache: balance["usdt"]
    )
    monkeypatch.setattr(main, "send", lambda msg: None)
    monkeypatch.setattr(main.strategy, "should_sell", lambda s, p, price, h: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda s, price, h: False)

    # First price increase
    main.trade()
    pos = db.get_open_positions()["BTCUSDT"]
    assert pos["trail_price"] == pytest.approx(110.0)
    assert pos["stop_loss"] == pytest.approx(
        110.0 * (1 - main.STOP_LOSS_PCT)
    )

    # Second price increase
    price_holder["price"] = 120.0
    main.trade()
    pos = db.get_open_positions()["BTCUSDT"]
    assert pos["trail_price"] == pytest.approx(120.0)
    assert pos["stop_loss"] == pytest.approx(
        120.0 * (1 - main.STOP_LOSS_PCT)
    )
