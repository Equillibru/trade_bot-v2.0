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
