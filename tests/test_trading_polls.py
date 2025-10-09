import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _setup_main(monkeypatch, tmp_path, trading_pairs='["BTCUSDT"]'):
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "secret")
    monkeypatch.setenv("NEWSAPI_KEY", "news")
    monkeypatch.setenv("TRADING_PAIRS", trading_pairs)
    monkeypatch.setenv("TRADE_DB_FILE", str(tmp_path / "trading.db"))

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
            return {"free": "100"}

        def get_symbol_ticker(self, symbol):
            return {"price": "100"}

        def get_klines(self, *args, **kwargs):
            return []

        def get_account(self):
            return {"balances": []}

        def create_order(self, *args, **kwargs):
            return {}

    monkeypatch.setattr(bc, "Client", DummyClient)

    main = importlib.import_module("main")
    monkeypatch.setattr(main, "preload_history", lambda symbols=None: None)
    monkeypatch.setattr(main, "get_usdt_balance", lambda: 1000.0)
    monkeypatch.setattr(main, "load_json", lambda path, default: {"usdt": 1000.0, "total": 1000.0})
    monkeypatch.setattr(main, "update_balance", lambda balance, positions, price_cache: balance["usdt"])
    monkeypatch.setattr(main, "get_news_headlines", lambda symbol: [])
    monkeypatch.setattr(main, "send", lambda msg: None)
    monkeypatch.setattr(main, "save_json", lambda path, data: None)
    main.PENDING_DECISIONS.clear()
    main.PENDING_POLLS.clear()
    return main


def test_strategy_buy_enqueues_poll(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 2.0)
    monkeypatch.setattr(
        main,
        "calculate_position_size",
        lambda *args, **kwargs: (1.0, 98.0, ""),
    )
    monkeypatch.setattr(main, "get_price", lambda symbol: 100.0)

    send_poll_mock = MagicMock(return_value="poll1")
    monkeypatch.setattr(main, "send_poll", send_poll_mock)
    place_order_mock = MagicMock()
    monkeypatch.setattr(main, "place_order", place_order_mock)

    main.trade()

    send_poll_mock.assert_called_once()
    place_order_mock.assert_not_called()
    assert "BTCUSDT" in main.PENDING_DECISIONS
    decision = main.PENDING_DECISIONS["BTCUSDT"]
    assert decision["action"] == "buy"
    assert decision["qty"] == 1.0


def test_poll_confirmation_executes_buy(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 2.0)
    monkeypatch.setattr(
        main,
        "calculate_position_size",
        lambda *args, **kwargs: (1.5, 98.5, ""),
    )
    monkeypatch.setattr(main, "get_price", lambda symbol: 99.0)

    poll_id = "poll2"
    monkeypatch.setattr(main, "send_poll", MagicMock(return_value=poll_id))
    place_order_mock = MagicMock(return_value={})
    monkeypatch.setattr(main, "place_order", place_order_mock)
    monkeypatch.setattr(main.db, "log_trade", lambda *args, **kwargs: 1)
    monkeypatch.setattr(main.db, "upsert_position", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "get_open_positions", lambda: {})

    main.trade()

    assert main.PENDING_POLLS[poll_id] == "BTCUSDT"
    decision = main.PENDING_DECISIONS["BTCUSDT"]
    decision["poll_id"] = poll_id

    main.finalize_pending_decision("BTCUSDT", True)

    place_order_mock.assert_called_once_with("BTCUSDT", "buy", 1.5)
    assert "BTCUSDT" not in main.PENDING_DECISIONS
    assert poll_id not in main.PENDING_POLLS

def test_poll_answer_update_executes_decision(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 1.5)
    monkeypatch.setattr(
        main,
        "calculate_position_size",
        lambda *args, **kwargs: (1.25, 97.5, ""),
    )
    monkeypatch.setattr(main, "get_price", lambda symbol: 101.0)

    poll_id = "poll-answer"
    monkeypatch.setattr(main, "send_poll", MagicMock(return_value=poll_id))
    place_order_mock = MagicMock(return_value={})
    monkeypatch.setattr(main, "place_order", place_order_mock)
    monkeypatch.setattr(main.db, "log_trade", lambda *args, **kwargs: 2)
    monkeypatch.setattr(main.db, "upsert_position", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "get_open_positions", lambda: {})

    main.trade()

    poll_answer = {"poll_id": poll_id, "option_ids": [0]}
    main._handle_poll_answer(poll_answer)

    place_order_mock.assert_called_once_with("BTCUSDT", "buy", 1.25)
    assert "BTCUSDT" not in main.PENDING_DECISIONS
    assert poll_id not in main.PENDING_POLLS


def test_strategy_sell_enqueues_poll(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    position = {
        "qty": 2.0,
        "entry": 90.0,
        "stop_loss": None,
        "take_profit": None,
        "trail_price": 90.0,
        "trade_id": 7,
        "stop_distance": None,
    }

    monkeypatch.setattr(main.db, "get_open_positions", lambda: {"BTCUSDT": position.copy()})
    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.strategy, "should_buy", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "get_price", lambda symbol: 95.0)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 2.0)
    monkeypatch.setattr(main, "send_poll", MagicMock(return_value="poll3"))
    place_order_mock = MagicMock()
    monkeypatch.setattr(main, "place_order", place_order_mock)

    main.trade()

    place_order_mock.assert_not_called()
    assert "BTCUSDT" in main.PENDING_DECISIONS
    assert main.PENDING_DECISIONS["BTCUSDT"]["action"] == "sell"
