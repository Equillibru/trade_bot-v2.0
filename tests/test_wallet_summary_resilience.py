import importlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED = [
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
    "NEWSAPI_KEY",
]


def load_main(monkeypatch):
    for var in REQUIRED:
        monkeypatch.setenv(var, "x")
    binance_mod = types.ModuleType("binance")
    client_mod = types.ModuleType("binance.client")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_asset_balance(self, asset="USDT"):
            return {"free": "0"}

        def get_margin_account(self):
            return {}

        def get_symbol_ticker(self, symbol):
            return {"price": "0"}

    client_mod.Client = DummyClient
    binance_mod.client = client_mod
    sys.modules["binance"] = binance_mod
    sys.modules["binance.client"] = client_mod
    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def _prepare_balance_file(tmp_path):
    balance_data = {"usdt": 150.0, "start_balance": 100.0}
    balance_file = tmp_path / "balance.json"
    balance_file.write_text(json.dumps(balance_data))
    return balance_file, balance_data


def test_wallet_summary_uses_stored_balance_when_fetch_returns_none(
    monkeypatch, tmp_path
):
    main = load_main(monkeypatch)

    balance_file, balance_data = _prepare_balance_file(tmp_path)

    monkeypatch.setattr(main, "get_usdt_balance", lambda: None)
    monkeypatch.setattr(main.db, "get_open_positions", lambda: {})

    summary = main.wallet_summary(balance_path=str(balance_file))

    assert summary["start_balance"] == pytest.approx(balance_data["start_balance"])
    assert summary["current_balance"] == pytest.approx(balance_data["usdt"])
    assert summary["positions"] == []


def test_wallet_summary_recovers_from_balance_errors(monkeypatch, tmp_path):
    main = load_main(monkeypatch)

    balance_file, balance_data = _prepare_balance_file(tmp_path)

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "get_usdt_balance", boom)
    monkeypatch.setattr(main.db, "get_open_positions", lambda: {})

    summary = main.wallet_summary(balance_path=str(balance_file))

    assert summary["start_balance"] == pytest.approx(balance_data["start_balance"])
    assert summary["current_balance"] == pytest.approx(balance_data["usdt"])
    assert summary["positions"] == []
