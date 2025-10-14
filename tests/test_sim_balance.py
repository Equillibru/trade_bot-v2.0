import importlib
import json
import sys
import types
from pathlib import Path

import pytest

REQUIRED_ENV_VARS = [
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
    "NEWSAPI_KEY",
]


@pytest.fixture
def main_module(monkeypatch, tmp_path):
    """Load the trading bot with external services stubbed."""

    # Avoid network requests during import
    requests = types.ModuleType("requests")
    requests.post = lambda *a, **k: types.SimpleNamespace(json=lambda: {})
    requests.get = lambda *a, **k: types.SimpleNamespace(json=lambda: {"articles": []})
    monkeypatch.setitem(sys.modules, "requests", requests)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)

    binance = types.ModuleType("binance")
    client_mod = types.ModuleType("binance.client")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_asset_balance(self, asset="USDT"):
            # Simulate an empty exchange wallet
            return {"free": "0"}

        def get_symbol_ticker(self, symbol="BTCUSDT"):
            return {"price": "10"}

        def get_account(self):
            return {"balances": []}

        def get_klines(self, *args, **kwargs):
            return []

        def create_order(self, *args, **kwargs):
            return {}

    client_mod.Client = DummyClient
    binance.client = client_mod
    monkeypatch.setitem(sys.modules, "binance", binance)
    monkeypatch.setitem(sys.modules, "binance.client", client_mod)

    for var in REQUIRED_ENV_VARS:
        monkeypatch.setenv(var, "x")

    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT"]))
    monkeypatch.setenv("TRADE_DB_FILE", str(tmp_path / "trades.db"))

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for mod in ["db", "main"]:
        if mod in sys.modules:
            del sys.modules[mod]
    import db  # noqa: WPS433 - imported for its side effects
    importlib.reload(db)
    main = importlib.import_module("main")
    importlib.reload(main)
    return main


def test_trade_uses_simulated_balance_when_exchange_empty(main_module, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "BALANCE_FILE", tmp_path / "balance.json")
    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)
    monkeypatch.setattr(main_module, "save_json", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "load_json", lambda *a, **k: {"usdt": main_module.START_BALANCE, "total": main_module.START_BALANCE})
    monkeypatch.setattr(main_module, "update_balance", lambda balance, positions, price_cache: balance["usdt"])
    monkeypatch.setattr(main_module, "get_news_headlines", lambda symbol: [])
    monkeypatch.setattr(main_module, "send", lambda msg: None)
    monkeypatch.setattr(main_module, "save_price", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "calculate_position_size", lambda *a, **k: (1.0, 9.5, None))
    monkeypatch.setattr(main_module, "get_stop_distance", lambda s, p: 0.5)
    monkeypatch.setattr(main_module, "get_price", lambda symbol: 10.0)

    main_module.WATCHLIST = ["BTCUSDT"]
    main_module.strategy.history["BTCUSDT"] = [9, 9, 9, 9, 9]

    main_module.trade()

    positions = main_module.db.get_open_positions()
    assert "BTCUSDT" in positions
    assert main_module.SIM_USDT_BALANCE > 0
    assert main_module.SIM_USDT_BALANCE < main_module.START_BALANCE
