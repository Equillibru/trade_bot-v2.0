import os
import time
import datetime
import json
import sqlite3
import requests
import math
from dotenv import load_dotenv
from binance.client import Client

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
# Toggle news-based trading filter via env var (default: True)
USE_NEWS_FILTER = os.getenv("USE_NEWS_FILTER", "True").lower() == "true"
START_BALANCE = 100.32  # Example starting balance
DAILY_MAX_INVEST = START_BALANCE * 0.20
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
TRADE_LOG_FILE = "trade_log.json"
MIN_TRADE_USDT = 0.10
MAX_TRADE_USDT = 10.0
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT", "PENGUUSDT", "TRXUSDT", 
                 "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT", "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", 
                 "CFXUSDT", "AAVEUSDT", "WIFUSDT", "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", 
                 "DOTUSDT", "CKBUSDT", "LINKUSDT", "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", 
                 "SHIBUSDT", "OPUSDT"]

bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
 # good_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"] - relaxing the news filter so trades proceed unless negative words are detected

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

    # fallback to last stored price if live request fails
    try:
        conn = sqlite3.connect("prices.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT price FROM prices WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        if row:
            price = row[0]
            print(f"Using cached price for {symbol}: {price}")
    except Exception as e:
        print(f"Price load error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

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
def update_balance(balance, positions, price_cache):
    """Recalculate total balance and persist it."""
    invested = sum(
        p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items()
    )
    total = balance["usdt"] + invested
    balance["total"] = total
    save_json(BALANCE_FILE, balance)
    return total

def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(
        BALANCE_FILE,
        {"usdt": START_BALANCE, "total": START_BALANCE},
    )
    balance.setdefault("usdt", START_BALANCE)
    balance.setdefault("total", balance["usdt"])
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    binance_usdt = get_usdt_balance()
    print(f"💵 Binance USDT balance: ${binance_usdt:.2f}")
    # Respect global USE_NEWS_FILTER setting which can be toggled via env var
    global USE_NEWS_FILTER

    price_cache = {}

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price or price <= 0:
            print(f"⚠️ {symbol} skipped — invalid price")
            continue

        price_cache[symbol] = price
        print(f"🔍 {symbol} @ ${price:.2f}")

        # Always evaluate open positions first using the latest price so
        # profits are realized even if news headlines are negative.
        if symbol in positions:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            pnl = ((price - entry) / entry) * 100
            profit = (price - entry) * qty

            print(f"📈 {symbol} Entry=${entry:.2f} → Now=${price:.2f} | PnL={pnl:.2f}%")

            if pnl >= 0.5:
                balance["usdt"] += qty * price
                del positions[symbol]
                log_trade(symbol, "CLOSE-LONG", qty, price)

                total = update_balance(balance, positions, price_cache)
                send(
                    f"✅ CLOSE {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) | Balance: ${balance['usdt']:.2f} — {now}"
                )
                print(f"✅ CLOSE {symbol} at ${price:.2f} | Profit: ${profit:.2f} USDT (+{pnl:.2f}%)")
                print(f"   ↳ Balance now ${balance['usdt']:.2f} USDT, Total ${total:.2f}")
            continue

        print(f"🔍 {symbol} @ ${price:.2f}")
        headlines = get_news_headlines(symbol)

        if USE_NEWS_FILTER and any(
            any(bad in h.lower() for bad in bad_words) for h in headlines
        ):
            print(f"🚫 {symbol} blocked — negative news detected")
            continue

    # Live cap enforcement: only 25% of START_BALANCE can be invested
        current_invested = sum(
            p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items()
        )
        remaining_allowance = START_BALANCE * 0.25 - current_invested
        print(
            f"💰 Balance: ${balance['usdt']:.2f}, Invested: ${current_invested:.2f}, Remaining cap: ${remaining_allowance:.2f}"
        )

        if remaining_allowance <= 0:
            print(f"🔒 Skipped {symbol} — daily investment cap reached")
            continue

        # Calculate qty (25% of USDT or remaining cap) with min/max bounds
        trade_usdt = min(balance["usdt"] * 0.25, remaining_allowance, MAX_TRADE_USDT)
        if trade_usdt < MIN_TRADE_USDT:
            print(f"❌ Trade amount {trade_usdt:.2f} USDT below minimum — skipping {symbol}")
            continue
            
        qty = math.floor((trade_usdt / price) * 1e6) / 1e6
        actual_usdt = qty * price

        print(f"🔢 {symbol} → trade_usdt={trade_usdt:.4f}, qty={qty}, value={actual_usdt:.4f}")

        if qty <= 0 or actual_usdt < MIN_TRADE_USDT:
            print(f"❌ Qty for {symbol} is zero or below minimum — skipping")
            continue
        if actual_usdt < 0.10 or actual_usdt > 10.00:
            print(f"⚠️ Skipped {symbol} — trade value ${actual_usdt:.4f} outside [0.10, 10.00] range")
            continue

        if actual_usdt > balance["usdt"]:
            print(f"❌ Skipped {symbol} — insufficient balance for ${actual_usdt:.2f}")
            continue

        positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
        balance["usdt"] -= actual_usdt
        log_trade(symbol, "BUY", qty, price)
            
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

    save_json(POSITION_FILE, positions)
    


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
