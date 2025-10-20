import os
import sys
import types
import json
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub external dependencies before importing main
requests_mock = types.ModuleType('requests')
requests_mock.post = MagicMock()
sys.modules['requests'] = requests_mock

dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = MagicMock()
sys.modules.setdefault('dotenv', dotenv)

binance_mod = types.ModuleType('binance')
client_mod = types.ModuleType('binance.client')
client_mod.Client = MagicMock()
binance_mod.client = client_mod
sys.modules.setdefault('binance', binance_mod)
sys.modules.setdefault('binance.client', client_mod)

os.environ.setdefault('TELEGRAM_TOKEN', 'token')
os.environ.setdefault('TELEGRAM_CHAT_ID', 'chat')
os.environ.setdefault('BINANCE_API_KEY', 'key')
os.environ.setdefault('BINANCE_SECRET_KEY', 'secret')
os.environ.setdefault('NEWSAPI_KEY', 'news')

import main


def test_send_poll(monkeypatch):
    # Prepare a mock for requests.post
    post_mock = MagicMock()
    monkeypatch.setattr(main.requests, 'post', post_mock)

    response = MagicMock()
    response.json.return_value = {"result": {"poll": {"id": "123"}}}
    response.raise_for_status = MagicMock()
    post_mock.return_value = response

    poll_id = main.send_poll('Question?', ['Yes', 'No'], is_anonymous=False)

    post_mock.assert_called_once()
    url = post_mock.call_args[0][0]
    data = post_mock.call_args.kwargs['data']
    assert url == f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendPoll"
    assert data['chat_id'] == os.environ['TELEGRAM_CHAT_ID']
    assert data['question'] == 'Question?'
    assert data['options'] == json.dumps(['Yes', 'No'])
    assert data['is_anonymous'] is False
    assert poll_id == "123"
    response.raise_for_status.assert_called_once()


def test_format_balance_breakdown_includes_positions():
    summary = {
        "start_balance": 100.0,
        "current_balance": 80.5,
        "positions": [
            {"symbol": "BTCUSDT", "qty": 0.5, "entry": 20000},
            {"symbol": "ETHUSDT", "qty": 1.25, "entry": 1500.1234},
        ],
    }

    message = main.format_balance_breakdown(summary)

    assert "Starting balance: $100.00" in message
    assert "Liquidity: $80.50" in message
    assert "BTCUSDT" in message and "0.5 @ $20000.00" in message
    assert "ETHUSDT" in message and "1.25 @ $1500.12" in message


def test_send_balance_breakdown_uses_wallet_summary(monkeypatch):
    summary = {
        "start_balance": 120.0,
        "current_balance": 95.0,
        "positions": [],
    }

    monkeypatch.setattr(main, "wallet_summary", lambda: summary)

    sent = {}

    def fake_send(msg):
        sent["msg"] = msg

    monkeypatch.setattr(main, "send", fake_send)

    main.send_balance_breakdown()

    assert "Starting balance: $120.00" in sent["msg"]
    assert "Positions: none" in sent["msg"]


def test_trade_prompt_mentions_balance(monkeypatch):
    main.PENDING_DECISIONS.clear()
    main.PENDING_POLLS.clear()

    decision = {"symbol": "BTCUSDT", "action": "buy", "price": 101.23}

    monkeypatch.setattr(main, "send_poll", lambda *a, **k: None)

    messages = []

    def fake_send(msg):
        messages.append(msg)

    monkeypatch.setattr(main, "send", fake_send)

    main._store_pending_decision(decision, "Proceed?")

    assert any("BALANCE" in msg for msg in messages)
