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


def test_strategy_buy_executes_without_poll(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    positions = {}
    monkeypatch.setattr(main.db, "get_open_positions", lambda: positions)

    def _upsert(symbol, qty, entry, stop_loss, take_profit, trade_id, trail_price, stop_distance):
        positions[symbol] = {
            "qty": qty,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trail_price": trail_price,
            "trade_id": trade_id,
            "stop_distance": stop_distance,
        }

    monkeypatch.setattr(main.db, "log_trade", lambda *args, **kwargs: 42)
    monkeypatch.setattr(main.db, "upsert_position", _upsert)

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 2.0)
    monkeypatch.setattr(main, "calculate_position_size", lambda *args, **kwargs: (1.0, 98.0, ""))
    monkeypatch.setattr(main, "get_price", lambda symbol: 100.0)

    send_poll_mock = MagicMock()
    monkeypatch.setattr(main, "send_poll", send_poll_mock)
    place_order_mock = MagicMock(return_value={})
    monkeypatch.setattr(main, "place_order", place_order_mock)

    main.trade()

    send_poll_mock.assert_not_called()
    place_order_mock.assert_called_once_with("BTCUSDT", "buy", 1.0)
    assert "BTCUSDT" in positions


def test_strategy_sell_loss_enqueues_poll(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    position = {
        "qty": 2.0,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": None,
        "trail_price": 100.0,
        "trade_id": 7,
        "stop_distance": 5.0,
    }
    positions = {"BTCUSDT": position.copy()}

    monkeypatch.setattr(main.db, "get_open_positions", lambda: positions)
    monkeypatch.setattr(main.db, "update_trade_pnl", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "remove_position", lambda symbol: positions.pop(symbol, None))


    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "get_price", lambda symbol: 94.0)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 5.0)
    
    send_poll_mock = MagicMock(return_value="poll3")
    monkeypatch.setattr(main, "send_poll", send_poll_mock)
    place_order_mock = MagicMock()
    monkeypatch.setattr(main, "place_order", place_order_mock)
    
    main.trade()

    place_order_mock.assert_not_called()
    assert "BTCUSDT" in main.PENDING_DECISIONS
    decision = main.PENDING_DECISIONS["BTCUSDT"]
    assert decision["reason"] == "stop_loss"
    send_poll_mock.assert_called_once()

    main.finalize_pending_decision("BTCUSDT", True)


def test_pending_decisions_support_multiple_symbols(monkeypatch, tmp_path):
    main = _setup_main(
        monkeypatch,
        tmp_path,
        trading_pairs='["BTCUSDT", "ETHUSDT"]',
    )

    position = {
        "qty": 2.0,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": None,
        "trail_price": 100.0,
        "trade_id": 7,
        "stop_distance": 5.0,
    }
    positions = {"ETHUSDT": position.copy()}

    monkeypatch.setattr(main.db, "get_open_positions", lambda: positions)
    monkeypatch.setattr(main.db, "update_trade_pnl", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "remove_position", lambda symbol: positions.pop(symbol, None))

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main.strategy, "should_buy", lambda *args, **kwargs: False)

    def _price(symbol):
        if symbol == "ETHUSDT":
            return 94.0
        if symbol == "BTCUSDT":
            return 100.0
        return 100.0

    monkeypatch.setattr(main, "get_price", _price)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 5.0)

    poll_id = "poll-eth"
    send_poll_mock = MagicMock(return_value=poll_id)
    monkeypatch.setattr(main, "send_poll", send_poll_mock)
    place_order_mock = MagicMock()
    monkeypatch.setattr(main, "place_order", place_order_mock)

    main.PENDING_DECISIONS.clear()
    main.PENDING_POLLS.clear()

    main.trade()

    place_order_mock.assert_not_called()
    assert "ETHUSDT" in main.PENDING_DECISIONS
    assert "BTCUSDT" not in main.PENDING_DECISIONS
    assert main.PENDING_POLLS[poll_id] == "ETHUSDT"

    decision = main.PENDING_DECISIONS["ETHUSDT"]
    decision["poll_id"] = poll_id

    main.finalize_pending_decision("ETHUSDT", True)

    place_order_mock.assert_called_once_with("ETHUSDT", "sell", 2.0)
    assert poll_id not in main.PENDING_POLLS
    assert "ETHUSDT" not in main.PENDING_DECISIONS

def test_strategy_sell_profit_executes_immediately(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    position = {
        "qty": 1.5,
        "entry": 90.0,
        "stop_loss": 80.0,
        "take_profit": None,
        "trail_price": 90.0,
        "trade_id": 12,
        "stop_distance": 10.0,
    }
    positions = {"BTCUSDT": position.copy()}

    monkeypatch.setattr(main.db, "get_open_positions", lambda: positions)
    monkeypatch.setattr(main.db, "update_trade_pnl", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "remove_position", lambda symbol: positions.pop(symbol, None))

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "get_price", lambda symbol: 110.0)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 10.0)

    send_poll_mock = MagicMock()
    monkeypatch.setattr(main, "send_poll", send_poll_mock)
    place_order_mock = MagicMock(return_value={})
    monkeypatch.setattr(main, "place_order", place_order_mock)


    main.trade()

    place_order_mock.assert_called_once_with("BTCUSDT", "sell", 1.5)
    send_poll_mock.assert_not_called()

    assert "BTCUSDT" not in main.PENDING_DECISIONS
def test_poll_answer_executes_pending_sell(monkeypatch, tmp_path):
    main = _setup_main(monkeypatch, tmp_path)

    position = {
        "qty": 1.0,
        "entry": 105.0,
        "stop_loss": 100.0,
        "take_profit": None,
        "trail_price": 105.0,
        "trade_id": 3,
        "stop_distance": 5.0,
    }
    positions = {"BTCUSDT": position.copy()}

    monkeypatch.setattr(main.db, "get_open_positions", lambda: positions)
    monkeypatch.setattr(main.db, "update_trade_pnl", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "remove_position", lambda symbol: positions.pop(symbol, None))

    monkeypatch.setattr(main.strategy, "should_sell", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "get_price", lambda symbol: 99.0)
    monkeypatch.setattr(main, "get_stop_distance", lambda s, p: 5.0)

    poll_id = "poll-stop"
    send_poll_mock = MagicMock(return_value=poll_id)
    monkeypatch.setattr(main, "send_poll", send_poll_mock)
    place_order_mock = MagicMock(return_value={})
    monkeypatch.setattr(main, "place_order", place_order_mock)

    main.trade()

    assert main.PENDING_POLLS[poll_id] == "BTCUSDT"
    decision = main.PENDING_DECISIONS["BTCUSDT"]
    decision["poll_id"] = poll_id

    poll_answer = {"poll_id": poll_id, "option_ids": [0]}
    main._handle_poll_answer(poll_answer)

    place_order_mock.assert_called_once_with("BTCUSDT", "sell", 1.0)
    assert poll_id not in main.PENDING_POLLS
    assert "BTCUSDT" not in main.PENDING_DECISIONS
