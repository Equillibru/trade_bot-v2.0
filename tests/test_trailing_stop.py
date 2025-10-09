import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bootstrap_main(monkeypatch, tmp_path, initial_prices, trading_pairs=None):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "s")
    monkeypatch.setenv("NEWSAPI_KEY", "n")
    if trading_pairs is None:
        trading_pairs = ["BTCUSDT"]
    monkeypatch.setenv("TRADING_PAIRS", json.dumps(trading_pairs))
    db_file = tmp_path / "trades.db"
    monkeypatch.setenv("TRADE_DB_FILE", str(db_file))

   
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
    monkeypatch.setattr(main, "preload_history", lambda symbols=None: None)
    monkeypatch.setattr(main, "get_usdt_balance", lambda: 1000.0)
    if isinstance(initial_prices, dict):
        default_price = next(iter(initial_prices.values()))
        price_holder = {
            symbol: float(initial_prices.get(symbol, default_price))
            for symbol in trading_pairs
        }
    else:
        price_holder = {symbol: float(initial_prices) for symbol in trading_pairs}

    def _get_price(symbol):
        return price_holder[symbol]

    monkeypatch.setattr(main, "get_price", _get_price)
    monkeypatch.setattr(main, "get_news_headlines", lambda symbol: [])
    monkeypatch.setattr(
        main, "update_balance", lambda balance, positions, price_cache: balance["usdt"]
    )
    monkeypatch.setattr(main, "send", lambda msg: None)
    monkeypatch.setattr(main.strategy, "should_sell", lambda s, p, price, h: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda s, price, h: False)

    return main, db, price_holder


def test_trailing_stop_updates(monkeypatch, tmp_path):
    main, db, price_holder = _bootstrap_main(monkeypatch, tmp_path, 102.0)
    trade_id = db.log_trade("BTCUSDT", "BUY", 1.0, 100.0)
    db.upsert_position("BTCUSDT", 1.0, 100.0, 98.0, 150.0, trade_id, 100.0, 2.0)

    main.trade()
    pos = db.get_open_positions()["BTCUSDT"]
    assert pos["trail_price"] == pytest.approx(102.0)
    assert pos["stop_loss"] == pytest.approx(100.0)
    assert pos["take_profit"] == pytest.approx(104.0)

    
    price_holder["BTCUSDT"] = 103.0
    main.trade()
    pos = db.get_open_positions()["BTCUSDT"]
    assert pos["trail_price"] == pytest.approx(103.0)
    assert pos["stop_loss"] == pytest.approx(101.0)
    assert pos["take_profit"] == pytest.approx(104.0)


def test_take_profit_positive_after_fees(monkeypatch, tmp_path):
    main, db, price_holder = _bootstrap_main(monkeypatch, tmp_path, 100.05)
    trade_id = db.log_trade("BTCUSDT", "BUY", 1.0, 100.0)
    db.upsert_position("BTCUSDT", 1.0, 100.0, 99.5, 120.0, trade_id, 100.0, 0.05)

    main.trade()
    pos = db.get_open_positions()["BTCUSDT"]
    entry = pos["entry"]
    take_profit = pos["take_profit"]
    net_profit = take_profit * (1 - main.FEE_RATE) - entry * (1 + main.FEE_RATE)

    assert net_profit > 0

def test_take_profit_does_not_block_buy(monkeypatch, tmp_path):
    prices = {"BTCUSDT": 110.0, "ETHUSDT": 50.0}
    main, db, price_holder = _bootstrap_main(
        monkeypatch, tmp_path, prices, trading_pairs=["BTCUSDT", "ETHUSDT"]
    )
    trade_id = db.log_trade("BTCUSDT", "BUY", 1.0, 100.0)
    db.upsert_position("BTCUSDT", 1.0, 100.0, 95.0, 105.0, trade_id, 100.0, 5.0)

    monkeypatch.setattr(
        main.strategy, "should_buy", lambda symbol, price, headlines: symbol == "ETHUSDT"
    )
    monkeypatch.setattr(
        main,
        "calculate_position_size",
        lambda *args, **kwargs: (0.3, 48.0, None),
    )

    price_holder["BTCUSDT"] = 110.0
    price_holder["ETHUSDT"] = 50.0

    main.trade()

    positions = db.get_open_positions()
    assert "BTCUSDT" not in positions
    assert positions["ETHUSDT"]["entry"] == pytest.approx(50.0)


def test_stop_skip_when_loss(monkeypatch, tmp_path):
    main, db, price_holder = _bootstrap_main(monkeypatch, tmp_path, 98.0)
    trade_id = db.log_trade("BTCUSDT", "BUY", 1.0, 100.0)
    db.upsert_position("BTCUSDT", 1.0, 100.0, 99.0, 150.0, trade_id, 100.0, 1.0)

    notifications = []
    monkeypatch.setattr(main, "send", lambda msg: notifications.append(msg))

    main.trade()

    positions = db.get_open_positions()
    assert "BTCUSDT" in positions
    assert any("skipped" in msg.lower() for msg in notifications)
