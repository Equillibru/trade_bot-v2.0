import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, List, Any, Optional

DB_FILE = os.getenv("TRADE_DB_FILE", "trading.db")

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                qty REAL,
                price REAL,
                timestamp TEXT,
                profit REAL,
                pnl_usdt REAL,
                pnl_pct REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                qty REAL,
                entry REAL,
                stop_loss REAL,
                opened_at TEXT,
                trade_id INTEGER
            )
            """
        )


def log_trade(symbol: str, side: str, qty: float, price: float) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (symbol, side, qty, price, timestamp)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (symbol, side, qty, price),
        )
        return cur.lastrowid


def update_trade_pnl(trade_id: int, pnl_usdt: float, pnl_pct: float) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE trades
            SET profit = ?, pnl_usdt = ?, pnl_pct = ?
            WHERE id = ?
            """,
            (pnl_usdt, pnl_usdt, pnl_pct, trade_id),
        )


def upsert_position(symbol: str, qty: float, entry: float, stop_loss: Optional[float], trade_id: int) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO positions (symbol, qty, entry, stop_loss, opened_at, trade_id)
            VALUES (?, ?, ?, ?, datetime('now'), ?)
            """,
            (symbol, qty, entry, stop_loss, trade_id),
        )


def remove_position(symbol: str) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))


def get_open_positions() -> Dict[str, Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT symbol, qty, entry, stop_loss, trade_id FROM positions")
        rows = cur.fetchall()
    return {
        row[0]: {
            "qty": row[1],
            "entry": row[2],
            "stop_loss": row[3],
            "trade_id": row[4],
        }
        for row in rows
    }


def get_trade_history(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        if symbol:
            cur.execute(
                "SELECT id, symbol, side, qty, price, timestamp, profit, pnl_usdt, pnl_pct FROM trades WHERE symbol = ? ORDER BY timestamp",
                (symbol,),
            )
        else:
            cur.execute(
                "SELECT id, symbol, side, qty, price, timestamp, profit, pnl_usdt, pnl_pct FROM trades ORDER BY timestamp"
            )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def average_profit_last_n_trades(n: int) -> float:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT AVG(pnl_pct) FROM (
                SELECT pnl_pct FROM trades
                WHERE pnl_pct IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT ?
            )
            """,
            (n,),
        )
        result = cur.fetchone()[0]
        return result or 0.0
