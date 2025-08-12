import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_update_trade_pnl_saves_profit(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    monkeypatch.setenv("TRADE_DB_FILE", str(db_file))
    if "db" in sys.modules:
        del sys.modules["db"]
    db = importlib.import_module("db")
    db.init_db()
    trade_id = db.log_trade("BTCUSDT", "BUY", 1.0, 100.0)
    db.update_trade_pnl(trade_id, 25.0, 0.25)
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT profit, pnl_usdt, pnl_pct FROM trades WHERE id = ?", (trade_id,))
        profit, pnl_usdt, pnl_pct = cur.fetchone()
    assert profit == pytest.approx(25.0)
    assert pnl_usdt == pytest.approx(25.0)
    assert pnl_pct == pytest.approx(0.25)
