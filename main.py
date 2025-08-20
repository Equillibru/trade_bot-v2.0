import os
import time
import datetime
import json
import sqlite3
import argparse
import db
import requests
import threading #Telegram two-way communication
# import math
from dotenv import load_dotenv
from binance.client import Client
from strategies.base import Strategy
from strategies.ma import MovingAverageCrossStrategy
from strategies.rsi import RSIStrategy
from risk import calculate_position_size

def _require_env_vars(names):
    """Ensure required environment variables are present."""
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise SystemExit(
            f"Missing required environment variables: {', '.join(missing)}"
        )

# === Load environment ===
load_dotenv()
os.environ.setdefault("NEWSAPI_KEY", "dummy")
_require_env_vars(
    [
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "BINANCE_API_KEY",
        "BINANCE_SECRET_KEY",
        "NEWSAPI_KEY",
    ]
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

LIVE_MODE = False
START_BALANCE = 100.32  # Example starting balance
DAILY_MAX_INVEST = START_BALANCE * 0.20

BALANCE_FILE = "balance.json"

MIN_TRADE_USDT = 1.0
MAX_TRADE_USDT = 10.0
RISK_PER_TRADE = 0.01  # risk 1% of available balance per trade
STOP_LOSS_PCT = 0.02   # 2% stop loss below entry
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT", "PENGUUSDT", "TRXUSDT", 
                 "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT", "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", 
                 "CFXUSDT", "AAVEUSDT", "WIFUSDT", "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", 
                 "DOTUSDT", "CKBUSDT", "LINKUSDT", "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", 
                 "SHIBUSDT", "OPUSDT"]

bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
 # good_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"] - relaxing the news filter so trades proceed unless negative words are detected
# Strategy selection via environment variable
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "ma").lower()
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", "1.0"))

def _init_strategy(name: str) -> Strategy:
    if name == "ma":
        return MovingAverageCrossStrategy(
            bad_words=bad_words, profit_target_pct=PROFIT_TARGET_PCT
        )
    if name == "rsi":
        return RSIStrategy(
            bad_words=bad_words, profit_target_pct=PROFIT_TARGET_PCT
        )
    raise ValueError(f"Unknown strategy '{name}'")
    


strategy: Strategy = _init_strategy(STRATEGY_NAME)
# Initialise database
db.init_db()

def call_with_retries(func, attempts=3, base_delay=1, name="request", alert=True):
    """Call a function with retries and exponential backoff."""
    for i in range(attempts):
        try:
            return func()
        except Exception as e:
            if i == attempts - 1:
                msg = f"{name} failed after {attempts} attempts: {e}"
                print(msg)
                if alert:
                    try:
                        send(f"⚠️ {msg}")
                    except Exception as send_err:
                        print(f"Error sending alert: {send_err}")
                return None
            time.sleep(base_delay * (2 ** i))

def send(msg):
    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)

    call_with_retries(_send, name="Telegram", alert=False)

def poll_telegram_commands():
    """Listen for manual trade commands sent via Telegram."""
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"timeout": 30, "offset": offset}
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                if str(chat_id) != str(TELEGRAM_CHAT_ID):
                    continue

                text = (msg.get("text") or "").strip()
                parts = text.split()
                if len(parts) != 3:
                    send("❓ Use BUY/SELL <symbol> <qty>")
                    continue

                cmd, symbol, qty_str = parts
                cmd = cmd.upper()
                symbol = symbol.upper()
                try:
                    qty = float(qty_str)
                except ValueError:
                    send("❓ Quantity must be numeric")
                    continue

                if cmd == "BUY":
                    price = get_price(symbol)
                    if not price or price <= 0:
                        send(f"⚠️ Invalid price for {symbol}")
                        continue

                    positions = db.get_open_positions()
                    balance = load_json(
                        BALANCE_FILE,
                        {"usdt": START_BALANCE, "total": START_BALANCE},
                    )
                    balance.setdefault("usdt", START_BALANCE)
                    actual_usdt = qty * price
                    if actual_usdt > balance["usdt"]:
                        send(f"⚠️ Insufficient balance for {symbol}")
                        continue

                    place_order(symbol, "buy", qty)
                    trade_id = db.log_trade(symbol, "BUY", qty, price)
                    db.upsert_position(symbol, qty, price, None, trade_id)
                    positions[symbol] = {
                        "qty": qty,
                        "entry": price,
                        "stop_loss": None,
                        "trade_id": trade_id,
                    }
                    balance["usdt"] -= actual_usdt
                    price_cache = {symbol: price}
                    update_balance(balance, positions, price_cache)
                    send(
                        f"🟢 BUY {qty} {symbol} at ${price:.2f} — Balance: ${balance['usdt']:.2f}"
                    )

                elif cmd == "SELL":
                    positions = db.get_open_positions()
                    if symbol not in positions:
                        send(f"⚠️ No open position for {symbol}")
                        continue
                    pos = positions[symbol]
                    if abs(pos["qty"] - qty) > 1e-6:
                        send(
                            f"⚠️ Position size {pos['qty']} {symbol}, cannot sell {qty}"
                        )
                        continue

                    price = get_price(symbol)
                    if not price or price <= 0:
                        send(f"⚠️ Invalid price for {symbol}")
                        continue

                    place_order(symbol, "sell", qty)
                    balance = load_json(
                        BALANCE_FILE,
                        {"usdt": START_BALANCE, "total": START_BALANCE},
                    )
                    balance.setdefault("usdt", START_BALANCE)
                    balance["usdt"] += qty * price
                    profit = (price - pos["entry"]) * qty
                    pnl_pct = (
                        (price - pos["entry"]) / pos["entry"] * 100
                        if pos["entry"]
                        else 0
                    )
                    trade_id = pos.get("trade_id")
                    db.update_trade_pnl(trade_id, profit, profit, pnl_pct)
                    db.remove_position(symbol)
                    del positions[symbol]
                    price_cache = {symbol: price}
                    update_balance(balance, positions, price_cache)
                    send(
                        f"🔴 SELL {qty} {symbol} at ${price:.2f} — PnL: ${profit:.2f} USDT ({pnl_pct:.2f}%)"
                    )

                else:
                    send("❓ Unknown command")

        except Exception as e:
            print(f"Telegram poll error: {e}")

        time.sleep(1)

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def wallet_summary(balance_path: str = BALANCE_FILE):
    """Return a snapshot of balances and open positions.

    Parameters
    ----------
    balance_path: str
        Path to the balance JSON file.

    Returns
    -------
    dict
        Dictionary with starting balance, current balance and a list of
        positions containing symbol, quantity and entry price.
    """
    data = load_json(balance_path, {"usdt": START_BALANCE, "start_balance": START_BALANCE})
    start_bal = data.get("start_balance", START_BALANCE)
    current_bal = data.get("usdt", start_bal)

    positions = db.get_open_positions()
    pos_list = [
        {"symbol": sym, "qty": info["qty"], "entry": info["entry"]}
        for sym, info in positions.items()
    ]

    summary = {
        "start_balance": start_bal,
        "current_balance": current_bal,
        "positions": pos_list,
    }

    return summary

# Get USDT balance from Binance
def get_usdt_balance():
    """Fetch available USDT balance from Binance."""
    def _get():
        bal = client.get_asset_balance(asset="USDT") or {}
        return float(bal.get("free", 0))

    return call_with_retries(_get, name="Binance USDT balance") or 0.0

def get_price(symbol):
    def _fetch():
        return float(client.get_symbol_ticker(symbol=symbol)["price"])

    price = call_with_retries(_fetch, name=f"Binance price {symbol}")
    if price is not None:
        save_price(symbol, price)
     
    return price
    
def place_order(symbol, side, qty):
    def _order():
        return client.create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=qty,
        )
    if LIVE_MODE:
        return call_with_retries(_order, name=f"Binance order {symbol}")
    else:
        print(f"[SIMULATED] {side} {qty} {symbol}")
        return {"simulated": True}

def get_news_headlines(symbol, limit=5):
    def _get():
        query = symbol.replace("USDT", "")
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "apiKey": NEWSAPI_KEY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": limit,
        }
        resp = requests.get(url, params=params, timeout=10)
        return resp.json()

    data = call_with_retries(_get, name=f"NewsAPI {symbol}") or {}
    return [a["title"] for a in data.get("articles", []) if "title" in a]


def save_price(symbol, price):
    """Persist price data with a timestamp into a SQLite database.

    The database keeps only a rolling window of recent prices for each symbol
    so that moving‑average calculations have sufficient history without the
    table growing indefinitely.
    """
    try:
        conn = sqlite3.connect("prices.db")
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS prices (timestamp TEXT, symbol TEXT, price REAL)"
        )
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cur.execute(
            "INSERT INTO prices (timestamp, symbol, price) VALUES (?, ?, ?)",
            (timestamp, symbol, price),
        )

        # keep a limited number of rows per symbol
        max_window = getattr(strategy, "long_window", 0)
        history_cap = max(max_window, getattr(strategy, "short_window", 0)) * 10 or 100
        cur.execute(
            """
            DELETE FROM prices
            WHERE symbol = ? AND rowid NOT IN (
                SELECT rowid FROM prices
                WHERE symbol = ?
                ORDER BY timestamp DESC, rowid DESC
                LIMIT ?
            )
            """,
            (symbol, symbol, history_cap),
        )
        conn.commit()
    except Exception as e:
        print(f"Price save error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def load_prices(symbol: str, limit: int):
    """Load the most recent ``limit`` prices for ``symbol`` from ``prices.db``."""
    try:
        conn = sqlite3.connect("prices.db")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT price FROM prices
            WHERE symbol = ?
            ORDER BY timestamp DESC, rowid DESC
            LIMIT ?
            """,
            (symbol, limit),
        )
        rows = [r[0] for r in cur.fetchall()]
        return list(reversed(rows))
    except Exception as e:
        print(f"Price load error: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def preload_history():
    """Populate the strategy's in-memory history from stored prices."""
    history_limit = max(
        getattr(strategy, "short_window", 0), getattr(strategy, "long_window", 0)
    )
    for sym in TRADING_PAIRS:
        prices = load_prices(sym, history_limit)
        if prices:
            strategy.history[sym] = prices
            
def update_balance(balance, positions, price_cache):
    """Recalculate total balance and persist it."""
    invested = sum(
        p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items()
    )
    total = balance["usdt"] + invested
    balance["total"] = total
    save_json(BALANCE_FILE, balance)
    return total

def sync_positions_with_exchange():
    """Reconcile database positions with live exchange holdings."""
    db_positions = db.get_open_positions()
    try:
        account = client.get_account()
        balances = {
            b["asset"]: float(b.get("free", 0)) + float(b.get("locked", 0))
            for b in account.get("balances", [])
        }
    except Exception as e:
        print(f"Position sync failed: {e}")
        return db_positions

    for symbol, pos in list(db_positions.items()):
        asset = symbol.replace("USDT", "")
        exch_qty = balances.get(asset, 0.0)
        if abs(exch_qty - pos["qty"]) > 1e-6:
            if exch_qty <= 0:
                db.remove_position(symbol)
                del db_positions[symbol]
            else:
                db.upsert_position(
                    symbol, exch_qty, pos["entry"], pos.get("stop_loss"), pos["trade_id"]
                )
                db_positions[symbol]["qty"] = exch_qty
    return db_positions

def trade():
    positions = db.get_open_positions()
    balance = load_json(
        BALANCE_FILE,
        {"usdt": START_BALANCE, "total": START_BALANCE},
    )
    balance.setdefault("usdt", START_BALANCE)
    balance.setdefault("total", balance["usdt"])
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    binance_usdt = get_usdt_balance()
    print(f"💵 Binance USDT balance: ${binance_usdt:.2f}")
    
    price_cache = {}
    preload_history()
    
    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price or price <= 0:
            print(f"⚠️ {symbol} skipped — invalid price")
            continue

        price_cache[symbol] = price
        print(f"🔍 {symbol} @ ${price:.2f}")
        headlines = get_news_headlines(symbol)

        # Check existing positions first using strategy rules
        if symbol in positions:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            stop = pos.get("stop_loss")
            pnl = ((price - entry) / entry) * 100
            profit = (price - entry) * qty

            print(f"📈 {symbol} Entry=${entry:.2f} → Now=${price:.2f} | PnL={pnl:.2f}%")

            if stop and price <= stop:
                order_info = place_order(symbol, "sell", qty)
                print(f"   ↳ order: {order_info}")
                balance["usdt"] += qty * price
                trade_id = pos.get("trade_id")
                db.update_trade_pnl(trade_id, profit, profit, pnl)
                db.remove_position(symbol)
                del positions[symbol]
                
                total = update_balance(balance, positions, price_cache)
                send(
                    f"🛑 STOP {symbol} at ${price:.2f} — PnL: ${profit:.2f} USDT ({pnl:.2f}%) | Balance: ${balance['usdt']:.2f} — {now}"
                )
                print(f"🛑 STOP {symbol} at ${price:.2f} | PnL: ${profit:.2f} USDT ({pnl:.2f}%)")
                print(f"   ↳ Balance now ${balance['usdt']:.2f} USDT, Total ${total:.2f}")
                continue

            if strategy.should_sell(symbol, pos, price, headlines):
                order_info = place_order(symbol, "sell", qty)
                print(f"   ↳ order: {order_info}")
                balance["usdt"] += qty * price
                trade_id = pos.get("trade_id")
                db.update_trade_pnl(trade_id, profit, profit, pnl)
                db.remove_position(symbol)
                del positions[symbol]
                
                total = update_balance(balance, positions, price_cache)
                send(
                    f"✅ CLOSE {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) | Balance: ${balance['usdt']:.2f} — {now}"
                )
                print(f"✅ CLOSE {symbol} at ${price:.2f} | Profit: ${profit:.2f} USDT (+{pnl:.2f}%)")
                print(f"   ↳ Balance now ${balance['usdt']:.2f} USDT, Total ${total:.2f}")
            continue

        # For new positions, defer decision to strategy
        if not strategy.should_buy(symbol, price, headlines):
            continue

        # Live cap enforcement: only 25% of START_BALANCE can be invested
        current_invested = sum(
            p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items()
        )
        remaining_allowance = DAILY_MAX_INVEST - current_invested
        print(
            f"💰 Balance: ${balance['usdt']:.2f}, Invested: ${current_invested:.2f}, Remaining cap: ${remaining_allowance:.2f}"
        )

        if remaining_allowance <= 0:
            print(f"🔒 Skipped {symbol} — daily investment cap reached")
            continue

        max_trade = min(remaining_allowance, MAX_TRADE_USDT)
        qty, stop_loss, reason = calculate_position_size(
            balance["usdt"],
            price,
            RISK_PER_TRADE,
            STOP_LOSS_PCT,
            MIN_TRADE_USDT,
            max_trade,
        )
       
        if qty <= 0:
            msg = reason or "position size too small"
            print(f"❌ Skipped {symbol} — {msg}")
            continue

        actual_usdt = qty * price

        if actual_usdt < MIN_TRADE_USDT:
            msg = reason or f"trade value ${actual_usdt:.2f} below minimum"
            print(f"❌ Skipped {symbol} — {msg}")
            continue
            
        stop_display = f"{stop_loss:.2f}" if stop_loss is not None else "0.0"
        print(f"🔢 {symbol} → qty={qty}, value={actual_usdt:.4f}, stop={stop_display}")

        if actual_usdt > balance["usdt"]:
            print(f"❌ Skipped {symbol} — insufficient balance for ${actual_usdt:.2f}")
            continue

        order_info = place_order(symbol, "buy", qty)
        print(f"   ↳ order: {order_info}")

        trade_id = db.log_trade(symbol, "BUY", qty, price)
        db.upsert_position(symbol, qty, price, stop_loss, trade_id)
        positions[symbol] = {
            "type": "LONG",
            "qty": qty,
            "entry": price,
            "stop_loss": stop_loss,
            "trade_id": trade_id,
        }
        balance["usdt"] -= actual_usdt
                    
        total = update_balance(balance, positions, price_cache)
        send(
            f"🟢 BUY {qty} {symbol} at ${price:.2f} — Value: ${actual_usdt:.2f} USDT | Remaining: ${balance['usdt']:.2f} — {now}"
        )
        print(f"✅ BUY {qty} {symbol} at ${price:.2f} (${actual_usdt:.2f})")  

    # Balance update
    total = update_balance(balance, positions, price_cache)
    send(
        f"📊 Updated Balance: ${balance['usdt']:.2f} (Total ${total:.2f}) — {now} | Binance USDT: ${binance_usdt:.2f}"
    )

    avg = db.average_profit_last_n_trades(10)
    print(f"📈 Avg profit last 10 trades: {avg:.2f}%")

def main():
    print("🤖 Trading bot started.")
    send("🤖 Trading bot is live.")
    sync_positions_with_exchange()
    threading.Thread(target=poll_telegram_commands, daemon=True).start()
    while True:
        try:
            trade()
        except Exception as e:
            print(f"ERROR: {e}")
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading bot")
    parser.add_argument(
        "--summary", action="store_true", help="Show wallet summary and exit"
    )
    args = parser.parse_args()
    if args.summary:
        print(json.dumps(wallet_summary(), indent=2))
    else:
        main()
