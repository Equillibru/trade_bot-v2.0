import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODULE_NAME = 'main'
REQUIRED = [
    'TELEGRAM_TOKEN',
    'TELEGRAM_CHAT_ID',
    'BINANCE_API_KEY',
    'BINANCE_SECRET_KEY',
    'NEWSAPI_KEY',
]


def reload_module():
    if MODULE_NAME in sys.modules:
        del sys.modules[MODULE_NAME]
    return importlib.import_module(MODULE_NAME)


def test_env_all_present(monkeypatch):
    for var in REQUIRED:
        monkeypatch.setenv(var, 'x')
    # Should not raise SystemExit when all vars present
    reload_module()


def test_missing_env_var(monkeypatch):
    for var in REQUIRED:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('TELEGRAM_TOKEN', 'token')
    with pytest.raises(SystemExit) as exc:
        reload_module()
    assert 'Missing required environment variables' in str(exc.value)
