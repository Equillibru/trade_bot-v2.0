import os
import time
import datetime
import json
import sqlite3
import argparse
import logging
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
DAILY_MAX_INVEST = START_BALANCE * 0.25

BALANCE_FILE = "balance.json"

# Simulated balance used when LIVE_MODE is False
SIM_USDT_BALANCE = START_BALANCE

MIN_TRADE_USDT = 1.0
MAX_TRADE_USDT = 20.0
RISK_PER_TRADE = 0.02  # risk 1% of available balance per trade
RISK_REWARD = 2.0
FEE_RATE = 0.001
MAX_ORDERS_PER_CYCLE = 1

# Volatility-based stop configuration
STOP_ATR_PERIOD = int(os.getenv("STOP_ATR_PERIOD", "14"))
STOP_ATR_MULT = float(os.getenv("STOP_ATR_MULT", "2.0"))

# Default trading pairs used when no configuration is supplied
DEFAULT_TRADING_PAIRS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT",
    "PENGUUSDT", "TRXUSDT", "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT",
    "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", "CFXUSDT", "AAVEUSDT",
    "WIFUSDT", "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", "DOTUSDT",
    "CKBUSDT", "LINKUSDT", "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT",
    "SHIBUSDT", "OPUSDT",
]


def load_trading_pairs() -> list[str]:
    """Load trading pairs from env var or JSON file.

    The environment variable ``TRADING_PAIRS`` may contain either a JSON array
    or a comma separated list.  If it is not provided, the loader will look for
    a JSON file specified by ``TRADING_PAIRS_CONFIG`` (defaulting to
    ``trading_pairs.json``).  If neither are supplied or parsing fails, the
    default pairs are returned.
    """

    env_pairs = os.getenv("TRADING_PAIRS")
    if env_pairs:
        try:
            pairs = json.loads(env_pairs)
            if isinstance(pairs, str):
                pairs = [p.strip() for p in pairs.split(",") if p.strip()]
        except json.JSONDecodeError:
            pairs = [p.strip() for p in env_pairs.split(",") if p.strip()]
        if isinstance(pairs, list) and pairs:
            return [str(p) for p in pairs]

    config_path = os.getenv("TRADING_PAIRS_CONFIG", "trading_pairs.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("trading_pairs", data)
            if isinstance(data, list):
                return [str(p) for p in data]
        except Exception:
            pass

    return DEFAULT_TRADING_PAIRS.copy()


# Static list of symbols to monitor for trading opportunities
WATCHLIST = load_trading_pairs()

bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
 # good_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"] - relaxing the news filter so trades proceed unless negative words are detected
# Strategy selection via environment variable
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "ma").lower()
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", "4.0"))

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
                logger.error(msg)
                if alert:
                    try:
                        send(f"⚠️ {msg}")
                    except Exception as send_err:
                        logger.error("Error sending alert: %s", send_err)
                return None
            time.sleep(base_delay * (2 ** i))

def get_atr(symbol: str, period: int) -> float | None:
    """Fetch Average True Range for ``symbol`` over ``period`` candles."""

    def _fetch():
        klines = client.get_klines(
            symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=period + 1
        )
        if not klines or len(klines) < period + 1:
            return None
        trs = []
        prev_close = float(klines[0][4])
        for k in klines[1:]:
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            tr = max(high, prev_close) - min(low, prev_close)
            trs.append(tr)
            prev_close = close
        return sum(trs) / len(trs) if trs else None

    return call_with_retries(_fetch, name=f"ATR {symbol}", alert=False)


def get_stop_distance(symbol: str, price: float) -> float:
    """Determine stop distance based on ATR and configuration."""

    period = int(os.getenv(f"STOP_ATR_PERIOD_{symbol}", STOP_ATR_PERIOD))
    mult = float(os.getenv(f"STOP_ATR_MULT_{symbol}", STOP_ATR_MULT))
    atr = get_atr(symbol, period)
    if not atr or price <= 0:
        return price * 0.02  # fallback to 2% if ATR unavailable
    return atr * mult

def send(msg):
    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)

    call_with_retries(_send, name="Telegram", alert=False)

def send_poll(question, options, **kwargs):
    """Send a poll message to the configured Telegram chat."""

    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "question": question,
            "options": json.dumps(options),
        }
        data.update(kwargs)
        requests.post(url, data=data, timeout=10)

    call_with_retries(_send, name="Telegram", alert=False)

def poll_telegram_commands():
    """Listen for manual trade commands sent via Telegram."""
    global SIM_USDT_BALANCE
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
                    send_poll("Select action", ["BUY", "SELL"])
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
                    binance_usdt = get_usdt_balance()
                    if binance_usdt <= 0:
                        binance_usdt = balance.get("usdt", START_BALANCE)
                    actual_cost = qty * price * (1 + FEE_RATE)
                    if actual_cost > binance_usdt:
                        send(f"⚠️ Insufficient balance for {symbol}")
                        continue

                    place_order(symbol, "buy", qty)
                    trade_id = db.log_trade(symbol, "BUY", qty, price)
                    db.upsert_position(symbol, qty, price, None, trade_id, price)
                    positions[symbol] = {
                        "qty": qty,
                        "entry": price,
                        "stop_loss": None,
                        "trail_price": price,
                        "trade_id": trade_id,
                    }
                    if not LIVE_MODE:
                        SIM_USDT_BALANCE -= actual_cost
                        client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}
                    price_cache = {symbol: price}
                    update_balance(balance, positions, price_cache)
                    binance_usdt = balance["usdt"]
                    send(
                        f"🟢 BUY {qty} {symbol} at ${price:.2f} — Cost: ${actual_cost:.2f} — Balance: ${binance_usdt:.2f}"
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
                    
                    entry_cost = pos["entry"] * qty * (1 + FEE_RATE)
                    sell_value = qty * price * (1 - FEE_RATE)
                    profit = sell_value - entry_cost
                    
                    pnl_pct = profit / entry_cost * 100 if entry_cost else 0
                    
                    trade_id = pos.get("trade_id")
                    db.update_trade_pnl(trade_id, profit, profit, pnl_pct)
                    db.remove_position(symbol)
                    del positions[symbol]
                    price_cache = {symbol: price}
                    if not LIVE_MODE:
                        SIM_USDT_BALANCE += sell_value
                        client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}
                    update_balance(balance, positions, price_cache)
                    binance_usdt = balance["usdt"]
                    send(
                        f"🔴 SELL {qty} {symbol} at ${price:.2f} — PnL: ${profit:.2f} USDT ({pnl_pct:.2f}%) — Balance: ${binance_usdt:.2f}"
                    )

                else:
                    send_poll("Unknown command", ["BUY", "SELL"])

        except Exception as e:
            logger.error("Telegram poll error: %s", e)

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
    current_bal = get_usdt_balance()
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
    """Fetch available USDT balance."""
    global SIM_USDT_BALANCE
    
    def _get():
        bal = client.get_asset_balance(asset="USDT") or {}
        return float(bal.get("free", 0))

    bal = call_with_retries(_get, name="Binance USDT balance")
    if bal is None:
        bal = SIM_USDT_BALANCE
    if not LIVE_MODE:
        SIM_USDT_BALANCE = bal
    return bal

def get_price(symbol):
    try:
        from price_stream import get_latest_price
    except Exception:
        def get_latest_price(_):
            return None

    price = get_latest_price(symbol)
    if price is None:
        def _fetch():
            return float(client.get_symbol_ticker(symbol=symbol)["price"])

        price = call_with_retries(_fetch, name=f"Binance price {symbol}")
    if price is not None:
        save_price(symbol, price)
    return price

def fetch_historical_prices(symbol: str, limit: int) -> list[float]:
    """Fetch recent historical closing prices for ``symbol``.

    The Binance 1-minute klines endpoint is queried and the closing price from
    each candle is stored in ``prices.db`` via :func:`save_price`. The returned
    list contains up to ``limit`` prices ordered oldest to newest. Network
    errors are handled via :func:`call_with_retries`.
    """

    def _fetch() -> list[tuple[int, float]]:
        klines = client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1MINUTE,
            limit=limit,
        )
        return [(int(k[0]), float(k[4])) for k in klines]

    data = call_with_retries(_fetch, name=f"Binance klines {symbol}") or []
    prices: list[float] = []
    for ts_ms, price in data:
        ts = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        save_price(symbol, price, ts)
        prices.append(price)
    return prices
    
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
        logger.info("[SIMULATED] %s %s %s", side, qty, symbol)
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


def save_price(symbol, price, timestamp: str | None = None):
    """Persist price data with a timestamp into a SQLite database.

    Parameters
    ----------
    symbol : str
        Trading pair symbol (e.g. ``BTCUSDT``).
    price : float
        Price to record.
    timestamp : str | None, optional
        ISO formatted timestamp for the price.  If ``None`` the current time is
        used.  Allowing an explicit timestamp lets historical price fetches
        backfill the database with accurate times.

    The database keeps only a rolling window of recent prices for each symbol so
    that moving‑average calculations have sufficient history without the table
    growing indefinitely.
    """
    
    try:
        conn = sqlite3.connect("prices.db")
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS prices (timestamp TEXT, symbol TEXT, price REAL)"
        )
        if timestamp is None:
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
        logger.error("Price save error: %s", e)
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
        logger.error("Price load error: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def preload_history(symbols=None):
    """Ensure strategy history and local DB contain recent prices.

    Parameters
    ----------
    symbols : iterable[str] | None
        Specific symbols to preload.  If ``None`` the global ``WATCHLIST`` is
        used.  Open positions may supply additional symbols so that sell logic
        can run even if a pair is later removed from the watchlist.
    """

    history_limit = max(
        getattr(strategy, "short_window", 0), getattr(strategy, "long_window", 0)
    )
    long_window = getattr(strategy, "long_window", 0)
    for sym in symbols or WATCHLIST:
        prices = load_prices(sym, history_limit)
        if len(prices) < history_limit:
            logger.info(
                "Preloading %s history: have %d, need %d", sym, len(prices), history_limit
            )
            fetched = fetch_historical_prices(sym, history_limit)
            prices = load_prices(sym, history_limit)
            
        if len(prices) < history_limit and fetched:
                # Fallback in case ``fetch_historical_prices`` didn't persist
                for p in fetched:
                    save_price(sym, p)
                prices = load_prices(sym, history_limit)

        if len(prices) < long_window:
            logger.warning(
                "Insufficient history for %s: have %d, need %d", sym, len(prices), long_window
            )
            continue

        if hasattr(strategy, "seed_history"):
            strategy.seed_history(sym, prices)
        else:
            strategy.history[sym] = prices
            
def update_balance(balance, positions, price_cache):
    """Recalculate total balance using live USDT value and persist it."""
    binance_usdt = get_usdt_balance()
    if binance_usdt <= 0:
        binance_usdt = balance.get("usdt", 0.0)
    invested = sum(
        p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items()
    )
    total = binance_usdt + invested
    balance["usdt"] = binance_usdt
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
        logger.error("Position sync failed: %s", e)
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
                    symbol,
                    exch_qty,
                    pos["entry"],
                    pos.get("stop_loss"),
                    pos["trade_id"],
                    pos.get("trail_price", pos["entry"]),
                )
                db_positions[symbol]["qty"] = exch_qty
    for p in db_positions.values():
        stop = p.get("stop_loss")
        trail = p.get("trail_price", p.get("entry"))
        p["stop_distance"] = trail - stop if stop is not None else None
    return db_positions

def trade():
    global SIM_USDT_BALANCE
    positions = db.get_open_positions()
    for p in positions.values():
        stop = p.get("stop_loss")
        trail = p.get("trail_price", p.get("entry"))
        p["stop_distance"] = trail - stop if stop is not None else None
    balance = load_json(
        BALANCE_FILE,
        {"usdt": START_BALANCE, "total": START_BALANCE},
    )
    balance.setdefault("total", balance.get("usdt", START_BALANCE))
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    binance_usdt = get_usdt_balance()
    if binance_usdt <= 0:
        binance_usdt = balance.get("usdt", START_BALANCE)
    balance["usdt"] = binance_usdt
    logger.info("💵 Binance USDT balance: $%.2f", binance_usdt)
    
    price_cache = {}
    symbols = list(WATCHLIST)
    for sym in positions.keys():
        if sym not in symbols:
            symbols.append(sym)
    try:
        preload_history(symbols)
    except TypeError:
        preload_history()

    orders_this_cycle = 0

    for symbol in symbols:
        if orders_this_cycle >= MAX_ORDERS_PER_CYCLE and symbol not in positions:
            continue

        price = get_price(symbol)
        if not price or price <= 0:
            logger.warning("⚠️ %s skipped — invalid price", symbol)
            continue

        price_cache[symbol] = price
        logger.info("🔍 %s @ $%.2f", symbol, price)
        headlines = get_news_headlines(symbol)

        # Check existing positions first using strategy rules
        if symbol in positions:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            trail = pos.get("trail_price", entry)
            stop_distance = pos.get("stop_distance")
            if stop_distance is None:
                stop_distance = get_stop_distance(symbol, price)
                pos["stop_distance"] = stop_distance
            if price > trail:
                trail = price
                stop = trail - stop_distance
                pos["trail_price"] = trail
                pos["stop_loss"] = stop
                db.upsert_position(
                    symbol, qty, entry, stop, pos.get("trade_id"), trail
                )
            else:
                stop = pos.get("stop_loss")
                
            entry_cost = entry * qty * (1 + FEE_RATE)
            current_value = price * qty * (1 - FEE_RATE)
            profit = current_value - entry_cost
            pnl = (profit / entry_cost) * 100

            logger.info(
                "📈 %s Entry=$%.2f → Now=$%.2f | PnL=%.2f%%",
                symbol,
                entry,
                price,
                pnl,
            )

            
            if stop and price <= stop:
                if orders_this_cycle < MAX_ORDERS_PER_CYCLE:
                    order_info = place_order(symbol, "sell", qty)
                    logger.info("   ↳ order: %s", order_info)
                    trade_id = pos.get("trade_id")
                    sell_value = current_value
                    db.update_trade_pnl(trade_id, profit, profit, pnl)
                    db.remove_position(symbol)
                    del positions[symbol]

                    if not LIVE_MODE:
                        SIM_USDT_BALANCE += sell_value
                        client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}

                    total = update_balance(balance, positions, price_cache)
                    binance_usdt = balance["usdt"]
                    send(
                        f"🛑 STOP {symbol} at ${price:.2f} — PnL: ${profit:.2f} USDT ({pnl:.2f}%) | Balance: ${binance_usdt:.2f} — {now}"
                    )
                    logger.info(
                        "🛑 STOP %s at $%.2f | PnL: $%.2f USDT (%.2f%%)",
                        symbol,
                        price,
                        profit,
                        pnl,
                    )
                    logger.info(
                        "   ↳ Balance now $%.2f USDT, Total $%.2f",
                        binance_usdt,
                        total,
                    )
                    orders_this_cycle += 1
                else:
                    logger.info("🚫 Order limit reached, skipping stop-loss for %s", symbol)
                continue

            if strategy.should_sell(symbol, pos, price, headlines):
                if orders_this_cycle < MAX_ORDERS_PER_CYCLE:
                    order_info = place_order(symbol, "sell", qty)
                    logger.info("   ↳ order: %s", order_info)
                    trade_id = pos.get("trade_id")
                    sell_value = current_value
                    db.update_trade_pnl(trade_id, profit, profit, pnl)
                    db.remove_position(symbol)
                    del positions[symbol]

                    if not LIVE_MODE:
                        SIM_USDT_BALANCE += sell_value
                        client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}

                    total = update_balance(balance, positions, price_cache)
                    binance_usdt = balance["usdt"]
                    send(
                        f"✅ CLOSE {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) | Balance: ${binance_usdt:.2f} — {now}"
                    )
                    logger.info(
                        "✅ CLOSE %s at $%.2f | Profit: $%.2f USDT (+%.2f%%)",
                        symbol,
                        price,
                        profit,
                        pnl,
                    )
                    logger.info(
                        "   ↳ Balance now $%.2f USDT, Total $%.2f",
                        binance_usdt,
                        total,
                    )
                    orders_this_cycle += 1
                else:
                    logger.info("🚫 Order limit reached, skipping close for %s", symbol)
                continue

            continue

        # For new positions, defer decision to strategy
        if orders_this_cycle >= MAX_ORDERS_PER_CYCLE:
            continue

        if not strategy.should_buy(symbol, price, headlines):
            continue

        # Live cap enforcement: only 25% of START_BALANCE can be invested
        current_invested = sum(
            p["qty"] * price_cache.get(sym, 0) for sym, p in positions.items()
        )
        remaining_allowance = DAILY_MAX_INVEST - current_invested
        logger.info(
            "💰 Balance: $%.2f, Invested: $%.2f, Remaining cap: $%.2f",
            binance_usdt,
            current_invested,
            remaining_allowance,
        )

        if remaining_allowance <= 0:
            logger.info("🔒 Skipped %s — daily investment cap reached", symbol)
            continue

        max_trade = min(remaining_allowance, MAX_TRADE_USDT)
        stop_distance = get_stop_distance(symbol, price)
        qty, stop_loss, reason = calculate_position_size(
            binance_usdt,
            price,
            RISK_PER_TRADE,
            stop_distance,
            MIN_TRADE_USDT,
            max_trade,
            fee_rate=FEE_RATE,
        )
       
        if qty <= 0:
            msg = reason or "position size too small"
            logger.info("❌ Skipped %s — %s", symbol, msg)
            continue

        actual_cost = qty * price * (1 + FEE_RATE)

        if actual_cost < MIN_TRADE_USDT:
            msg = reason or f"trade value ${actual_cost:.2f} below minimum"
            logger.info("❌ Skipped %s — %s", symbol, msg)
            continue

        
        stop_display = f"{stop_loss:.2f}" if stop_loss is not None else "0.0"
        logger.info(
            "🔢 %s → qty=%s, value=%.4f, stop=%s",
            symbol,
            qty,
            actual_cost,
            stop_display,
        )

        if actual_cost > binance_usdt:
            msg = reason or f"insufficient balance for ${actual_cost:.2f}"
            logger.warning("❌ Skipped %s — %s", symbol, msg)
            continue

        order_info = place_order(symbol, "buy", qty)
        logger.info("   ↳ order: %s", order_info)

        trade_id = db.log_trade(symbol, "BUY", qty, price)
        db.upsert_position(symbol, qty, price, stop_loss, trade_id, price)
        positions[symbol] = {
            "type": "LONG",
            "qty": qty,
            "entry": price,
            "stop_loss": stop_loss,
            "trail_price": price,
            "trade_id": trade_id,
            "stop_distance": price - stop_loss if stop_loss is not None else stop_distance,
        }

        if not LIVE_MODE:
            SIM_USDT_BALANCE -= actual_cost
            client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}

        total = update_balance(balance, positions, price_cache)
        binance_usdt = balance["usdt"]
        send(
            f"🟢 BUY {qty} {symbol} at ${price:.2f} — Value: ${actual_cost:.2f} USDT | Remaining: ${binance_usdt:.2f} — {now}"
        )
        logger.info(
            "✅ BUY %s %s at $%.2f ($%.2f)", qty, symbol, price, actual_cost
        )
        orders_this_cycle += 1
        continue

    # Balance update
    total = update_balance(balance, positions, price_cache)
    binance_usdt = balance["usdt"]
    send(
        f"📊 Updated Balance: ${binance_usdt:.2f} (Total ${total:.2f}) — {now}"
    )

    avg = db.average_profit_last_n_trades(10)
    logger.info("📈 Avg profit last 10 trades: %.2f%%", avg)

def main():
    logger.info("🤖 Trading bot started.")
    send("🤖 Trading bot is live.")
    positions = sync_positions_with_exchange()

    # Seed initial price history so strategies can act on the first cycle
    preload_symbols = list(WATCHLIST)
    for sym in positions.keys():
        if sym not in preload_symbols:
            preload_symbols.append(sym)
    try:
        preload_history(preload_symbols)
    except TypeError:
        preload_history()

    threading.Thread(target=poll_telegram_commands, daemon=True).start()
    while True:
        try:
            trade()
        except Exception as e:
            logger.exception("ERROR: %s", e)
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading bot")
    parser.add_argument(
        "--summary", action="store_true", help="Show wallet summary and exit"
    )
    args = parser.parse_args()
    if args.summary:
        logger.info(json.dumps(wallet_summary(), indent=2))
    else:
        main()
