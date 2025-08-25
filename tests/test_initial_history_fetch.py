import importlib
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
            return {"free": "0"}

        def get_symbol_ticker(self, symbol="BTCUSDT"):
            return {"price": "0"}

        def create_order(self, *args, **kwargs):
            return {}

        def get_account(self):
            return {"balances": []}

        def get_klines(self, *args, **kwargs):
            return []

    monkeypatch.setattr(binance_client, "Client", DummyClient)
    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def test_initial_history_allows_first_trade(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADING_PAIRS", '["BTCUSDT"]')
    main = setup_main(monkeypatch, tmp_path)

    monkeypatch.setattr(main, "BALANCE_FILE", tmp_path / "balance.json")
    monkeypatch.setattr(main, "get_price", lambda s: 15.0)
    monkeypatch.setattr(main, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(main, "send", lambda msg: None)
    monkeypatch.setattr(main, "calculate_position_size", lambda *a, **k: (1.0, None, None))
    monkeypatch.setattr(main, "get_usdt_balance", lambda: 1000.0)
    monkeypatch.setattr(main, "load_json", lambda path, default: default)
    monkeypatch.setattr(main, "save_json", lambda path, data: None)
    monkeypatch.setattr(main, "update_balance", lambda balance, positions, price_cache: balance["usdt"])
    monkeypatch.setattr(main, "fetch_historical_prices", lambda sym, limit: [10, 11, 12, 13, 14])

    main.trade()

    positions = main.db.get_open_positions()
    assert "BTCUSDT" in positions
    assert len(main.strategy.history["BTCUSDT"]) >= main.strategy.long_window
