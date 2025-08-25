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
    main.TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT", "PENGUUSDT", "TRXUSDT", 
                 "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT", "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", 
                 "CFXUSDT", "AAVEUSDT", "WIFUSDT", "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", 
                 "DOTUSDT", "CKBUSDT", "LINKUSDT", "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", 
                 "SHIBUSDT", "OPUSDT"]

    for i in range(60):
        main.save_price("BTCUSDT", float(i))
        main.save_price("ETHUSDT", float(100 + i))
        main.save_price("XRPUSDT", float(100 + i))
        main.save_price("SOLUSDT", float(100 + i))
        main.save_price("DOGEUSDT", float(100 + i))
        main.save_price("ENAUSDT", float(100 + i))
        main.save_price("PENGUUSDT", float(100 + i))
        main.save_price("TRXUSDT", float(100 + i))
        main.save_price("ADAUSDT", float(100 + i))
        main.save_price("PEPEUSDT", float(100 + i))
        main.save_price("BONKUSDT", float(100 + i))
        main.save_price("LTCUSDT", float(100 + i))
        main.save_price("BNBUSDT", float(100 + i))
        main.save_price("AVAXUSDT", float(100 + i))
        main.save_price("XLMUSDT", float(100 + i))
        main.save_price("UNIUSDT", float(100 + i))
        main.save_price("CFXUSDT", float(100 + i))
        main.save_price("AAVEUSDT", float(100 + i))
        main.save_price("WIFUSDT", float(100 + i))
        main.save_price("KERNELUSDT", float(100 + i))
        main.save_price("BCHUSDT", float(100 + i))
        main.save_price("ARBUSDT", float(100 + i))
        main.save_price("ENSUSDT", float(100 + i))
        main.save_price("DOTUSDT", float(100 + i))
        main.save_price("CKBUSDT", float(100 + i))
        main.save_price("LINKUSDT", float(100 + i))
        main.save_price("TONUSDT", float(100 + i))
        main.save_price("NEARUSDT", float(100 + i))
        main.save_price("ETCUSDT", float(100 + i))
        main.save_price("CAKEUSDT", float(100 + i))
        main.save_price("SHIBUSDT", float(100 + i))
        main.save_price("OPUSDT", float(100 + i))

    # each symbol should keep only the most recent 50 prices
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT", "PENGUUSDT", "TRXUSDT", 
                 "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT", "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", 
                 "CFXUSDT", "AAVEUSDT", "WIFUSDT", "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", 
                 "DOTUSDT", "CKBUSDT", "LINKUSDT", "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", 
                 "SHIBUSDT", "OPUSDT"):
        cur.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", (sym,))
        assert cur.fetchone()[0] == 50
    conn.close()
    conn.close()

    prices_btc = main.load_prices("BTCUSDT", 5)
    prices_eth = main.load_prices("ETHUSDT", 5)
    prices_xrp = main.load_prices("XRPUSDT", 5)
    prices_sol = main.load_prices("SOLUSDT", 5)
    prices_doge = main.load_prices("DOGEUSDT", 5)
    prices_ena = main.load_prices("ENAUSDT", 5)
    prices_pengu = main.load_prices("PENGUUSDT", 5)
    prices_trx = main.load_prices("TRXUSDT", 5)
    prices_ada = main.load_prices("ADAUSDT", 5)
    prices_pepe = main.load_prices("PEPEUSDT", 5)
    prices_bonk = main.load_prices("BONKUSDT", 5)
    prices_ltc = main.load_prices("LTCUSDT", 5)
    prices_bnb = main.load_prices("BNBUSDT", 5)
    prices_ava = main.load_prices("AVAXUSDT", 5)
    prices_xlm = main.load_prices("XLMUSDT", 5)
    prices_uni = main.load_prices("UNIUSDT", 5)
    prices_cfx = main.load_prices("CFXUSDT", 5)
    prices_aave = main.load_prices("AAVEUSDT", 5)
    prices_wif = main.load_prices("WIFUSDT", 5)
    prices_kernel = main.load_prices("KERNELUSDT", 5)
    prices_bch = main.load_prices("BCHUSDT", 5)
    prices_arb = main.load_prices("ARBUSDT", 5)
    prices_ens = main.load_prices("ENSUSDT", 5)
    prices_dot = main.load_prices("DOTUSDT", 5)
    prices_ckb = main.load_prices("CKBUSDT", 5)
    prices_link = main.load_prices("LINKUSDT", 5)
    prices_ton = main.load_prices("TONUSDT", 5)
    prices_near = main.load_prices("NEARUSDT", 5)
    prices_etc = main.load_prices("ETCUSDT", 5)
    prices_cake = main.load_prices("CAKEUSDT", 5)
    prices_shib = main.load_prices("SHIBUSDT", 5)
    prices_op = main.load_prices("OPUSDT", 5)
            
    assert prices_btc == [55.0, 56.0, 57.0, 58.0, 59.0]
    assert prices_eth == [155.0, 156.0, 157.0, 158.0, 159.0]

    main.preload_history()
    assert main.strategy.history["BTCUSDT"] == prices_btc
    assert main.strategy.history["ETHUSDT"] == prices_eth
    assert main.strategy.history["XRPUSDT"] == prices_xrp
    assert main.strategy.history["SOLUSDT"] == prices_sol
    assert main.strategy.history["DOGEUSDT"] == prices_doge
    assert main.strategy.history["ENAUSDT"] == prices_ena
    assert main.strategy.history["PENGUUSDT"] == prices_pengu
    assert main.strategy.history["TRXUSDT"] == prices_trx
    assert main.strategy.history["ADAUSDT"] == prices_ada
    assert main.strategy.history["PEPUSDT"] == prices_pepe
    assert main.strategy.history["BONKUSDT"] == prices_bonk
    assert main.strategy.history["LTCUSDT"] == prices_ltc
    assert main.strategy.history["BNBUSDT"] == prices_bnb
    assert main.strategy.history["AVAXUSDT"] == prices_ava
    assert main.strategy.history["XLMUSDT"] == prices_xlm
    assert main.strategy.history["UNIUSDT"] == prices_uni
    assert main.strategy.history["CFXUSDT"] == prices_cfx
    assert main.strategy.history["AAVEUSDT"] == prices_aave
    assert main.strategy.history["WIFUSDT"] == prices_wif
    assert main.strategy.history["KERNELUSDT"] == prices_kernel
    assert main.strategy.history["BCHUSDT"] == prices_bch
    assert main.strategy.history["ARBUSDT"] == prices_arb
    assert main.strategy.history["EnsUSDT"] == prices_ens
    assert main.strategy.history["DOTUSDT"] == prices_dot
    assert main.strategy.history["CKBUSDT"] == prices_ckb
    assert main.strategy.history["LINKUSDT"] == prices_link
    assert main.strategy.history["TONUSDT"] == prices_ton
    assert main.strategy.history["NEARUSDT"] == prices_near
    assert main.strategy.history["ETCUSDT"] == prices_etc
    assert main.strategy.history["CAKEUSDT"] == prices_cake
    assert main.strategy.history["SHIBUSDT"] == prices_shib
    assert main.strategy.history["OPUSDT"] == prices_op
