import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_watchlist_persists_after_no_trades(monkeypatch, tmp_path):
    # set required environment variables
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "s")
    monkeypatch.setenv("NEWSAPI_KEY", "n")
    monkeypatch.setenv("TRADING_PAIRS", '["BTCUSDT"]')
    db_file = tmp_path / "trades.db"
    monkeypatch.setenv("TRADE_DB_FILE", str(db_file))

    # ensure clean modules
    for mod in ["db", "main"]:
        if mod in sys.modules:
            del sys.modules[mod]

    db = importlib.import_module("db")
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
    monkeypatch.setattr(main, "save_json", lambda path, data: None)
    monkeypatch.setattr(main, "preload_history", lambda symbols=None: None)
    monkeypatch.setattr(main, "get_usdt_balance", lambda: 1000.0)
    calls = {"count": 0}
    def fake_get_price(sym):
        calls["count"] += 1
        return 100.0
    monkeypatch.setattr(main, "get_price", fake_get_price)
    monkeypatch.setattr(main, "get_news_headlines", lambda s: [])
    monkeypatch.setattr(main.strategy, "should_sell", lambda s, p, price, h: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda s, price, h: False)
    monkeypatch.setattr(main, "update_balance", lambda balance, positions, price_cache: balance["usdt"])
    monkeypatch.setattr(main, "send", lambda msg: None)

    main.trade()
    assert calls["count"] == len(main.WATCHLIST)

    main.trade()
    assert calls["count"] == 2 * len(main.WATCHLIST)
