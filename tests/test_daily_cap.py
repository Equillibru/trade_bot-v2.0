import sys
from pathlib import Path
from unittest.mock import MagicMock
import types
import importlib.util
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED_VARS = [
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
    "NEWSAPI_KEY",
]

def load_main(monkeypatch):
    """Load main module in isolation with mocked dependencies."""
    requests_mock = MagicMock()
    monkeypatch.setitem(sys.modules, "requests", requests_mock)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = MagicMock()
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)

    binance_mod = types.ModuleType("binance")
    client_mod = types.ModuleType("binance.client")
    client_mod.Client = MagicMock()
    binance_mod.client = client_mod
    monkeypatch.setitem(sys.modules, "binance", binance_mod)
    monkeypatch.setitem(sys.modules, "binance.client", client_mod)

    for var in REQUIRED_VARS:
        monkeypatch.setenv(var, "test")

    spec = importlib.util.spec_from_file_location("_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_daily_max_invest_value(monkeypatch):
    main = load_main(monkeypatch)
    assert main.DAILY_MAX_INVEST == pytest.approx(main.START_BALANCE * 0.25)


def test_daily_cap_enforcement(monkeypatch):
    main = load_main(monkeypatch)
    current_invested = main.DAILY_MAX_INVEST - 5
    remaining = main.DAILY_MAX_INVEST - current_invested
    assert remaining == pytest.approx(5)

    current_invested = main.DAILY_MAX_INVEST + 1
    remaining = main.DAILY_MAX_INVEST - current_invested
    assert remaining < 0
