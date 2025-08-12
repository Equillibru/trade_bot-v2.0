import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def setup_main(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in [
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "BINANCE_API_KEY",
        "BINANCE_SECRET_KEY",
        "NEWSAPI_KEY",
    ]:
        monkeypatch.setenv(var, "x")

    from binance import client as binance_client

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_asset_balance(self, asset="USDT"):
            return {"free": 0}

        def get_symbol_ticker(self, symbol="BTCUSDT"):
            return {"price": "0"}

        def create_order(self, *args, **kwargs):
            return {}

        def get_account(self):
            return {"balances": []}

    monkeypatch.setattr(binance_client, "Client", DummyClient)
    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def test_save_and_load_prices(monkeypatch, tmp_path):
    main = setup_main(monkeypatch, tmp_path)

    for i in range(60):
        main.save_price("BTCUSDT", float(i))

    # should keep only the most recent 50 prices
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", ("BTCUSDT",))
    count = cur.fetchone()[0]
    assert count == 50
    conn.close()

    prices = main.load_prices("BTCUSDT", 5)
    assert prices == [55.0, 56.0, 57.0, 58.0, 59.0]

    main.preload_history()
    assert main.strategy.history["BTCUSDT"] == prices
