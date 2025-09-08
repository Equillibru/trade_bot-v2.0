import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_take_profit_realized_pnl_positive(monkeypatch, tmp_path):
    """Ensure realized PnL is positive when take-profit triggers."""
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

    import db
    db.init_db()

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
    monkeypatch.setattr(main, "load_json", lambda path, default: default)
    monkeypatch.setattr(main, "preload_history", lambda symbols=None: None)
    monkeypatch.setattr(main, "get_usdt_balance", lambda: 1000.0)
    price_holder = {"price": 100.0}
    monkeypatch.setattr(main, "get_price", lambda symbol: price_holder["price"])
    monkeypatch.setattr(main, "get_news_headlines", lambda symbol: [])
    monkeypatch.setattr(main, "update_balance", lambda balance, positions, price_cache: balance["usdt"])
    monkeypatch.setattr(main, "send", lambda msg: None)
    monkeypatch.setattr(main, "place_order", lambda *args, **kwargs: {})
    monkeypatch.setattr(main.strategy, "should_sell", lambda s, p, price, h: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda s, price, h: True)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, price: 2.0)
    monkeypatch.setattr(
        main,
        "calculate_position_size",
        lambda *args, **kwargs: (1.0, price_holder["price"] - 2.0, ""),
    )

    # Open position
    main.trade()
    pos = db.get_open_positions()["BTCUSDT"]
    take_profit = pos["take_profit"]
    assert take_profit > price_holder["price"]

    # Hit take-profit
    price_holder["price"] = take_profit
    monkeypatch.setattr(main.strategy, "should_buy", lambda s, price, h: False)
    main.trade()

    trade = db.get_trade_history("BTCUSDT")[0]
    assert trade["profit"] > 0
