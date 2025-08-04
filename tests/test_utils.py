import importlib
import sys
import types
from pathlib import Path

import pytest

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def main_module(monkeypatch):
    """Import the main module with external dependencies mocked."""
    # Stub requests
    req = types.ModuleType("requests")
    req.post = lambda *a, **k: None
    req.get = lambda *a, **k: types.SimpleNamespace(json=lambda: {"articles": []})
    sys.modules.setdefault("requests", req)

    # Stub dotenv
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None
    sys.modules.setdefault("dotenv", dotenv)

    # Stub binance client
    binance = types.ModuleType("binance")
    client_mod = types.ModuleType("binance.client")
    class DummyClient:
        def __init__(self, *a, **k):
            pass
        def get_symbol_ticker(self, symbol):
            return {"price": "1"}
        def get_asset_balance(self, asset):
            return {"free": "100"}
            
    client_mod.Client = DummyClient
    binance.client = client_mod
    sys.modules.setdefault("binance", binance)
    sys.modules.setdefault("binance.client", client_mod)

    module = importlib.import_module("main")
    importlib.reload(module)
    return module

# --- Tests -----------------------------------------------------------------

def test_load_and_save_json(tmp_path, main_module):
    path = tmp_path / "test.json"
    default = {"a": 1}
    # load should create file with default
    data = main_module.load_json(path, default)
    assert data == default
    assert path.exists()

    # save new data
    new_data = {"b": 2}
    main_module.save_json(path, new_data)
    assert main_module.load_json(path, {}) == new_data


def test_log_trade(tmp_path, monkeypatch, main_module):
    log_path = tmp_path / "log.json"
    monkeypatch.setattr(main_module, "TRADE_LOG_FILE", log_path)
    main_module.log_trade("BTCUSDT", "BUY", 1.0, 100)
    log = main_module.load_json(log_path, [])
    assert log and log[0]["symbol"] == "BTCUSDT"


def test_trade_buy_logic(tmp_path, monkeypatch, main_module):
    pos = tmp_path / "positions.json"
    bal = tmp_path / "balance.json"
    log = tmp_path / "trade_log.json"

    monkeypatch.setattr(main_module, "POSITION_FILE", pos)
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setattr(main_module, "TRADE_LOG_FILE", log)
    monkeypatch.setattr(main_module, "TRADING_PAIRS", ["BTCUSDT"])

    # Stub helpers
    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    sent = []
    monkeypatch.setattr(main_module, "send", lambda msg: sent.append(msg))

    main_module.trade()

    positions = main_module.load_json(pos, {})
    assert "BTCUSDT" in positions
    log_data = main_module.load_json(log, [])
    assert any(entry["type"] == "BUY" for entry in log_data)
    assert sent  # a telegram message was "sent"

def test_trade_with_no_headlines(tmp_path, monkeypatch, main_module):
    pos = tmp_path / "positions.json"
    bal = tmp_path / "balance.json"
    log = tmp_path / "trade_log.json"

    monkeypatch.setattr(main_module, "POSITION_FILE", pos)
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setattr(main_module, "TRADE_LOG_FILE", log)
    monkeypatch.setattr(main_module, "TRADING_PAIRS", ["BTCUSDT"])

    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: [])
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    main_module.trade()

    positions = main_module.load_json(pos, {})
    assert "BTCUSDT" in positions


def test_trade_with_neutral_headlines(tmp_path, monkeypatch, main_module):
    pos = tmp_path / "positions.json"
    bal = tmp_path / "balance.json"
    log = tmp_path / "trade_log.json"

    monkeypatch.setattr(main_module, "POSITION_FILE", pos)
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setattr(main_module, "TRADE_LOG_FILE", log)
    monkeypatch.setattr(main_module, "TRADING_PAIRS", ["BTCUSDT"])

    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(
        main_module,
        "get_news_headlines",
        lambda s: ["crypto markets update"],
    )
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    main_module.trade()

    positions = main_module.load_json(pos, {})
    assert "BTCUSDT" in positions


def test_balance_total_updates(tmp_path, monkeypatch, main_module):
    pos = tmp_path / "positions.json"
    bal = tmp_path / "balance.json"
    log = tmp_path / "trade_log.json"

    monkeypatch.setattr(main_module, "POSITION_FILE", pos)
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setattr(main_module, "TRADE_LOG_FILE", log)
    monkeypatch.setattr(main_module, "TRADING_PAIRS", ["BTCUSDT"])

    prices = [10000.0, 11000.0]
    monkeypatch.setattr(main_module, "get_price", lambda s: prices.pop(0))
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    main_module.trade()  # open
    main_module.trade()  # close with profit

    balance = main_module.load_json(bal, {})
    assert balance["usdt"] > main_module.START_BALANCE
    assert balance["total"] == pytest.approx(balance["usdt"])  # no open positions


def test_balance_persists_after_each_trade(tmp_path, monkeypatch, main_module):
    pos = tmp_path / "positions.json"
    bal = tmp_path / "balance.json"
    log = tmp_path / "trade_log.json"

    monkeypatch.setattr(main_module, "POSITION_FILE", pos)
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setattr(main_module, "TRADE_LOG_FILE", log)
    monkeypatch.setattr(main_module, "TRADING_PAIRS", ["BTCUSDT"])

    prices = [10000.0, 11000.0]
    monkeypatch.setattr(main_module, "get_price", lambda s: prices.pop(0))
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    main_module.trade()  # buy
    first_bal = main_module.load_json(bal, {})
    assert first_bal["usdt"] < main_module.START_BALANCE
    assert pytest.approx(first_bal["total"], rel=1e-5) == main_module.START_BALANCE

    main_module.trade()  # sell
    second_bal = main_module.load_json(bal, {})
    assert second_bal["usdt"] > first_bal["usdt"]
    assert second_bal["total"] == pytest.approx(second_bal["usdt"])  # no open positions

def test_get_usdt_balance(monkeypatch, main_module):
    monkeypatch.setattr(
        main_module.client, "get_asset_balance", lambda asset: {"free": "42.0"}
    )
    assert main_module.get_usdt_balance() == 42.0
