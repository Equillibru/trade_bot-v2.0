import importlib
import logging
import sys
import types
from pathlib import Path
import json
import pytest

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def main_module(monkeypatch, tmp_path):
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
        def get_asset_balance(self, asset):
            return {"free": "100"}
            
    client_mod.Client = DummyClient
    binance.client = client_mod
    sys.modules.setdefault("binance", binance)
    sys.modules.setdefault("binance.client", client_mod)

    monkeypatch.setenv("TRADE_DB_FILE", str(tmp_path / "trades.db"))
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    import db
    importlib.reload(db)
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


def test_log_trade(main_module):
    trade_id = main_module.db.log_trade("BTCUSDT", "BUY", 1.0, 100)
    hist = main_module.db.get_trade_history("BTCUSDT")
    assert hist and hist[0]["id"] == trade_id


def test_trade_buy_logic(tmp_path, monkeypatch, main_module, caplog):
    
    bal = tmp_path / "balance.json"
    
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"]))
    main_module.WATCHLIST = main_module.load_trading_pairs()

    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)
  
    # Stub helpers
    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    sent = []
    monkeypatch.setattr(main_module, "send", lambda msg: sent.append(msg))

      # build price history so strategy has sufficient data
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]

    with caplog.at_level(logging.INFO, logger="main"):
        main_module.trade()

    positions = main_module.db.get_open_positions()
    assert "BTCUSDT" in positions
    trades = main_module.db.get_trade_history("BTCUSDT")
    assert any(entry["side"] == "BUY" for entry in trades)
    assert sent  # a telegram message was "sent"
    assert any("BUY" in r.message for r in caplog.records)

def test_trade_with_no_headlines(tmp_path, monkeypatch, main_module):
    
    bal = tmp_path / "balance.json"
    
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"]))
    main_module.WATCHLIST = main_module.load_trading_pairs()

    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)

    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: [])
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    # prepopulate history to trigger buy
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]

    main_module.trade()

    positions = main_module.db.get_open_positions()
    assert "BTCUSDT" in positions


def test_trade_with_neutral_headlines(tmp_path, monkeypatch, main_module):
    
    bal = tmp_path / "balance.json"
   
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"]))
    main_module.WATCHLIST = main_module.load_trading_pairs()
    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)

    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(
        main_module,
        "get_news_headlines",
        lambda s: ["crypto markets update"],
    )
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    # ensure enough price history for a buy signal
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.trade()

    positions = main_module.db.get_open_positions()
    assert "BTCUSDT" in positions


def test_balance_total_updates(tmp_path, monkeypatch, main_module):
    
    bal = tmp_path / "balance.json"
    
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"]))
    main_module.TRADING_PAIRS = main_module.load_trading_pairs()
    monkeypatch.setattr(main_module, "preload_history", lambda: None)

    prices = [10000.0, 11000.0]
    monkeypatch.setattr(main_module, "get_price", lambda s: prices.pop(0))
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(main_module, "send", lambda msg: None)
    monkeypatch.setattr(main_module, "get_usdt_balance", lambda: main_module.SIM_USDT_BALANCE)
    monkeypatch.setattr(
        main_module.client,
        "get_asset_balance",
        lambda asset: {"free": str(main_module.START_BALANCE)},
    )
    monkeypatch.setattr(main_module.strategy, "should_buy", lambda s, price, h: True)
    monkeypatch.setattr(main_module.strategy, "should_sell", lambda s, pos, price, h: True)

    # seed history to allow first trade to execute
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]
    
    main_module.trade()  # open
    main_module.trade()  # close with profit

    balance = main_module.load_json(bal, {})
    assert balance["usdt"] > main_module.START_BALANCE
    assert balance["total"] == pytest.approx(balance["usdt"])  # no open positions
    assert main_module.db.get_open_positions() == {}


def test_balance_persists_after_each_trade(tmp_path, monkeypatch, main_module):
    
    bal = tmp_path / "balance.json"
    
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"]))
    main_module.WATCHLIST = main_module.load_trading_pairs()
    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)

    prices = [10000.0, 11000.0]
    monkeypatch.setattr(main_module, "get_price", lambda s: prices.pop(0))
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(main_module, "send", lambda msg: None)
    

    monkeypatch.setattr(
        main_module.client,
        "get_asset_balance",
        lambda asset: {"free": str(main_module.START_BALANCE)},
    )
    monkeypatch.setattr(main_module.strategy, "should_buy", lambda s, price, h: True)
    monkeypatch.setattr(main_module.strategy, "should_sell", lambda s, pos, price, h: True)

    # provide history for moving averages
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]
    
    main_module.trade()  # buy
    first_bal = main_module.load_json(bal, {})
    assert first_bal["usdt"] < main_module.START_BALANCE
    assert first_bal["total"] == pytest.approx(main_module.START_BALANCE, rel=1e-3)

    main_module.trade()  # sell
    second_bal = main_module.load_json(bal, {})
    assert second_bal["usdt"] > first_bal["usdt"]
    assert second_bal["total"] == pytest.approx(second_bal["usdt"])  # no open positions
    assert main_module.db.get_open_positions() == {}

def test_get_usdt_balance(monkeypatch, main_module):
    monkeypatch.setattr(
        main_module.client, "get_asset_balance", lambda asset: {"free": "42.0"}
    )
    assert main_module.get_usdt_balance() == 42.0

def test_trade_skips_when_position_size_zero(tmp_path, monkeypatch, main_module):
    
    bal = tmp_path / "balance.json"
    
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)    
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"]))
    main_module.WATCHLIST = main_module.load_trading_pairs()
    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)

    monkeypatch.setattr(main_module, "get_price", lambda s: 10000.0)
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(
        main_module,
        "calculate_position_size",
        lambda *a, **k: (0.0, None, "forced zero"),
    )
    monkeypatch.setattr(main_module, "get_stop_distance", lambda s, p: 1.0)
    monkeypatch.setattr(main_module, "send", lambda msg: None)

    # history ensures strategy would buy if size were nonzero
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]
    
    main_module.trade()

    positions = main_module.db.get_open_positions()
    assert "BTCUSDT" not in positions
    trades = main_module.db.get_trade_history("BTCUSDT")
    assert not trades

def test_trade_handles_multiple_pairs(tmp_path, monkeypatch, main_module):
    bal = tmp_path / "balance.json"
    monkeypatch.setattr(main_module, "BALANCE_FILE", bal)

    monkeypatch.setenv(
        "TRADING_PAIRS", json.dumps(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
                                                      "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
                                                      "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT", "WIFUSDT",
                                                      "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT", "CKBUSDT", "LINKUSDT",
                                                      "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", "SHIBUSDT", "OPUSDT"])
    )
    main_module.WATCHLIST = main_module.load_trading_pairs()
    monkeypatch.setattr(main_module, "preload_history", lambda symbols=None: None)
    monkeypatch.setattr(main_module, "MIN_TRADE_USDT", 0.5)

    prices = {"BTCUSDT": 10000.0, "ETHUSDT": 2000.0}
    monkeypatch.setattr(main_module, "get_price", lambda s: prices[s])
    monkeypatch.setattr(main_module, "get_news_headlines", lambda s: ["rally"])
    monkeypatch.setattr(main_module, "send", lambda msg: None)
    monkeypatch.setattr(main_module, "get_stop_distance", lambda s, p: 1.0)
    monkeypatch.setattr(main_module, "calculate_position_size", lambda *a, **k: (0.001, None, None))
    monkeypatch.setattr(main_module.strategy, "should_buy", lambda s, price, h: True)

    # seed price history for both symbols
    main_module.strategy.history["BTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XRPUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SOLUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOGEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PENGUUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TRXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ADAUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["PEPEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BONKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LTCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BNBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AVAXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["XLMUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["UNIUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CFXUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["AAVEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["WIFUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["KERNELUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["BCHUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ARBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ENSUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["DOTUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CKBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["LINKUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["TONUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["NEARUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["ETCUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["CAKEUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["SHIBUSDT"] = [9996, 9997, 9998, 9999]
    main_module.strategy.history["OPUSDT"] = [9996, 9997, 9998, 9999]

    main_module.trade()

    positions = main_module.db.get_open_positions()
    assert set(positions.keys()).issubset(main_module.WATCHLIST)

