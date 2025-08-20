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
            self.calls = []

        def get_symbol_ticker(self, symbol):
            self.calls.append(symbol)
            return {"price": "123.45"}

        def get_asset_balance(self, asset="USDT"):
            return {"free": 0}

    dummy = DummyClient()
    monkeypatch.setattr(binance_client, "Client", lambda *a, **k: dummy)

    if "main" in sys.modules:
        del sys.modules["main"]
    module = importlib.import_module("main")
    return module, dummy


def test_get_price_requests_and_saves(monkeypatch, tmp_path):
    main, dummy = setup_main(monkeypatch, tmp_path)

    price1 = main.get_price("BTCUSDT")
    price2 = main.get_price("BTCUSDT")

    assert price1 == 123.45
    assert price2 == 123.45
    assert dummy.calls == ["BTCUSDT", "BTCUSDT"]

    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", ("BTCUSDT",))
    count = cur.fetchone()[0]
    conn.close()

    assert count == 2
