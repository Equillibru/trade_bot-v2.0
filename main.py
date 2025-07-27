import os
import time
import datetime
import json
import sqlite3
import requests
import math
from dotenv import load_dotenv
from binance.client import Client

# === Load environment ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

LIVE_MODE = True
START_BALANCE = 100.32  # Example starting balance
DAILY_MAX_INVEST = START_BALANCE * 0.20
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
TRADE_LOG_FILE = "trade_log.json"
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT"]

bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
good_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"]

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
    def_send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)

    call_with_retries(_send, name="Telegram", alert=False)

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

def get_price(symbol):
    def _fetch():
        return float(client.get_symbol_ticker(symbol=symbol)["price"])

    price = call_with_retries(_fetch, name=f"Binance price {symbol}")
    if price is not None:
        save_price(symbol, price)
        
def place_order(symbol, side, qty):
    def_order():
        return client.create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=qty,
        )
    else:
        print(f"[SIMULATED] {side} {qty} {symbol}")
        return {"simulated": True}

def get_news_headlines(symbol, limit=5):
    def_get():
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

def log_trade(symbol, typ, qty, price):
    log = load_json(TRADE_LOG_FILE, [])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log.append({"symbol": symbol, "type": typ, "qty": qty, "price": price, "timestamp": timestamp})
    save_json(TRADE_LOG_FILE, log)

def save_price(symbol, price):
    """Persist price data with a timestamp into a SQLite database."""
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
        conn.commit()
    except Exception as e:
        print(f"Price save error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BALANCE})
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    
    # Optimization: fetch prices once for all traded/held symbols to avoid
    # redundant API calls during this trading cycle
    price_cache = {sym: get_price(sym) for sym in set(TRADING_PAIRS) | set(positions.keys())}

    # Calculate current invested amount using cached prices outside the loop
    current_invested = sum(p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items())
    remaining_allowance = DAILY_MAX_INVEST - current_invested
    
    for symbol in TRADING_PAIRS:
        price = price_cache.get(symbol)
        if not price:
            print(f"⚠️ No price for {symbol}")
            continue
        
        print(f"🔍 {symbol} @ ${price:.2f}")

        headlines = get_news_headlines(symbol)
        if any(any(bad in h.lower() for bad in bad_words) for h in headlines):
            print(f"🚫 {symbol} blocked by negative news")
            continue
        if not any(any(good in h.lower() for good in good_words) for h in headlines):
            print(f"🟡 {symbol} skipped — no strong positive news")
            #continue

        # Daily max check uses allowance calculated before the loop
      
        if remaining_allowance <= 0:
            print(f"🔒 Daily investment cap reached — skipping {symbol}")
            continue

        # Calculate qty (25% of USDT or remaining cap)
        trade_usdt = min(balance["usdt"] * 0.25, remaining_allowance)
        qty = math.floor((trade_usdt / price) * 1e6) / 1e6
        print(f"🔢 {symbol} → trade_usdt: {trade_usdt:.4f}, price: {price:.2f}, qty: {qty}")
        if qty <= 0:
            print(f"❌ Qty for {symbol} is zero — skipping")
            continue

        if symbol not in positions:
            if qty <= 0 or qty * price > balance["usdt"]:
                print(f"❌ Cannot buy {symbol} — qty too low or insufficient funds")
                continue

            positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
            balance["usdt"] -= qty * price
            remaining_allowance -= qty * price  # update allowance after buying
            log_trade(symbol, "BUY", qty, price)

            total_cost = qty * price
            send(f"🟢 BUY {qty} {symbol} at ${price:.2f} — Total: ${total_cost:.2f} USDT — {now}")
            print(f"✅ BUY {qty} {symbol} at ${price:.2f} (${total_cost:.2f})")

        else:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            pnl = ((price - entry) / entry) * 100
            profit = (price - entry) * qty

            print(f"📈 {symbol} Entry ${entry:.2f} → Now ${price:.2f} | PnL: {pnl:.2f}%")

            if pnl >= 0.5:
                balance["usdt"] += qty * price
                remaining_allowance += qty * price  # update allowance after closing
                del positions[symbol]
                log_trade(symbol, "CLOSE-LONG", qty, price)

                send(f"✅ CLOSE {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) — {now}")
                print(f"✅ CLOSE {symbol} at ${price:.2f} | Profit: ${profit:.2f} USDT (+{pnl:.2f}%)")

        # Update and report balance
        # Use cached prices to avoid extra API requests when calculating balance
        invested = sum(p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items())
        total = balance["usdt"] + invested
        send(f"📊 Updated Balance: ${total:.2f} USDT — {now}")

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

def main():
    print("🤖 Trading bot started.")
    send("🤖 Trading bot is live.")
    while True:
        try:
            trade()
        except Exception as e:
            print(f"ERROR: {e}")
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
