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

def _getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(
            "Invalid integer for %s: %s. Using default %s.", name, value, default
        )
        return default


def _getenv_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(
            "Invalid float for %s: %s. Using default %.3f.", name, value, default
        )
        return default

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

TRADING_MODE = os.getenv("TRADING_MODE", "spot").strip().lower()
SUPPORTED_TRADING_MODES = {"spot", "margin"}
if TRADING_MODE not in SUPPORTED_TRADING_MODES:
    raise SystemExit(
        "TRADING_MODE must be one of 'spot' or 'margin' (case-insensitive), "
        f"got: {TRADING_MODE!r}"
    )

MARGIN_SIDE_EFFECT_TYPE = os.getenv("MARGIN_SIDE_EFFECT_TYPE", "").strip().upper()

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
MIN_EXIT_PNL_PCT =1.0
MAX_ORDERS_PER_CYCLE = 1

BALANCE_REMINDER_INTERVAL_SECONDS = _getenv_int(
    "BALANCE_REMINDER_INTERVAL_SECONDS", 3 * 60 * 60
)
BALANCE_PRICE_SHIFT_THRESHOLD = _getenv_float(
    "BALANCE_PRICE_SHIFT_THRESHOLD", 0.05
)
BALANCE_REMINDER_INTERVAL = datetime.timedelta(
    seconds=BALANCE_REMINDER_INTERVAL_SECONDS
)

QUIET_HOURS_START = 20  # 20:00
QUIET_HOURS_END = 9  # 09:00

LAST_BALANCE_REMINDER: datetime.datetime | None = None
PRICE_BASELINE: dict[str, float] = {}

# In-memory record of trade actions awaiting manual confirmation via Telegram
PENDING_DECISIONS: dict[str, dict] = {}
PENDING_POLLS: dict[str, str] = {}

def is_within_quiet_hours(dt: datetime.datetime) -> bool:
    """Return True when the provided datetime falls within quiet hours."""

    local_dt = dt.astimezone()
    current_minutes = local_dt.hour * 60 + local_dt.minute
    start_minutes = QUIET_HOURS_START * 60
    end_minutes = QUIET_HOURS_END * 60

    if QUIET_HOURS_START <= QUIET_HOURS_END:
        return start_minutes <= current_minutes < end_minutes

    return current_minutes >= start_minutes or current_minutes < end_minutes

def calculate_fee_adjusted_take_profit(
    entry: float,
    stop: float | None,
    trail: float | None,
    fee_rate: float,
    risk_reward: float,
    min_exit_pnl_pct: float,
) -> float:
    """Return a take-profit price that stays profitable after fees.

    The helper keeps the original risk-reward target anchored at the entry
    price, but adjusts it whenever the exchange fees would otherwise erase the
    profit. The new stop price is used to measure the actual downside if the
    stop were triggered after fees, ensuring the adjusted target still respects
    the configured risk-reward multiple while guaranteeing that the realized
    profit clears the configured ``min_exit_pnl_pct`` threshold on execution.
    """

    if stop is None:
        stop = entry
    if trail is None:
        trail = stop

    entry_cost = entry * (1 + fee_rate)
    stop_value = stop * (1 - fee_rate)
    risk_after_fees = max(entry_cost - stop_value, 0.0)
    risk_distance =max(trail - stop, 0.0)

    base_target = entry + risk_distance * risk_reward
    required_profit = max(
        risk_after_fees * risk_reward,
        entry * (min_exit_pnl_pct / 100.0),
    )

    net_profit = base_target * (1 - fee_rate) - entry_cost
    if net_profit < required_profit:
        base_target = (entry_cost + required_profit) / (1 - fee_rate)

    return base_target

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

def _init_strategy(name: str) -> Strategy:
    if name == "ma":
        return MovingAverageCrossStrategy(
            bad_words=bad_words,
            fee_rate=FEE_RATE,
            min_pnl_pct=MIN_EXIT_PNL_PCT,
        )
    if name == "rsi":
        return RSIStrategy(
            bad_words=bad_words,
            fee_rate=FEE_RATE,
            min_pnl_pct=MIN_EXIT_PNL_PCT,
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
    """Send a poll message to the configured Telegram chat.

    Returns
    -------
    str | None
        The Telegram poll identifier when available.  ``None`` is returned if
        the API response cannot be parsed (e.g. during tests with simplified
        mocks).
    """

    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "question": question,
            "options": json.dumps(options),
        }
        data.update(kwargs)
        resp = requests.post(url, data=data, timeout=10)
        try:
            resp.raise_for_status()
        except AttributeError:
            # Lightweight mocks used in tests might not implement
            # ``raise_for_status``.
            pass
        except Exception:
            raise
        try:
            return resp.json()
        except Exception:
            return None

    result = call_with_retries(_send, name="Telegram", alert=False)
    if isinstance(result, dict):
        poll = result.get("result", {}).get("poll") or result.get("poll")
        if isinstance(poll, dict):
            return poll.get("id")
    return None


def _store_pending_decision(decision: dict, question: str) -> None:
    """Persist a pending trade decision and notify the operator."""

    symbol = decision["symbol"]
    if symbol in PENDING_DECISIONS:
        logger.info("⏳ Awaiting existing decision for %s", symbol)
        return

    poll_id = send_poll(
        question,
        ["Confirm", "Decline"],
        is_anonymous=False,
    )
    if poll_id:
        decision["poll_id"] = poll_id
        PENDING_POLLS[poll_id] = symbol

    PENDING_DECISIONS[symbol] = decision
    action = decision["action"].upper()
    price = decision["price"]
    send(
        (
            f"🤔 {action} {symbol} at ${price:.2f}? Reply 'CONFIRM {symbol}' or 'DECLINE {symbol}' or answer the poll."
            "\n💡 Send 'BALANCE' at any time to see the latest wallet summary."
        )
    )
    logger.info("🤔 Pending %s decision for %s", action, symbol)


def finalize_pending_decision(symbol: str, approved: bool) -> bool:
    """Execute or clear a pending decision once the user responds.

    Returns ``True`` if a pending decision existed for ``symbol``.
    """

    decision = PENDING_DECISIONS.pop(symbol, None)
    if not decision:
        logger.info("ℹ️ No pending decision for %s", symbol)
        return False

    poll_id = decision.get("poll_id")
    if poll_id:
        PENDING_POLLS.pop(poll_id, None)

    if approved:
        _execute_decision(decision)
    else:
        action = decision["action"].upper()
        price = decision["price"]
        send(f"🚫 Declined {action} {symbol} at ${price:.2f}")
        logger.info("🚫 Declined %s %s", action, symbol)
    return True


def _execute_decision(decision: dict) -> None:
    """Run the stored trade flow for a confirmed decision."""

    global SIM_USDT_BALANCE

    symbol = decision["symbol"]
    action = decision["action"]
    price = decision["price"]
    now = decision.get("timestamp") or datetime.datetime.now(
        datetime.timezone.utc
    ).strftime('%Y-%m-%d %H:%M')

    balance = load_json(
        BALANCE_FILE,
        {"usdt": START_BALANCE, "total": START_BALANCE},
    )

    if action == "buy":
        qty = decision["qty"]
        stop_loss = decision.get("stop_loss")
        take_profit = decision.get("take_profit")
        stop_distance = decision.get("stop_distance")
        actual_cost = decision.get("actual_cost", qty * price)
        order_info = place_order(symbol, "buy", qty)
        logger.info("   ↳ order: %s", order_info)

        trade_id = db.log_trade(symbol, "BUY", qty, price)
        db.upsert_position(
            symbol,
            qty,
            price,
            stop_loss,
            take_profit,
            trade_id,
            price,
            stop_distance,
        )
        if not LIVE_MODE:
            SIM_USDT_BALANCE -= actual_cost
            client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}

        positions = db.get_open_positions()
        price_cache = {symbol: price}
        total = update_balance(balance, positions, price_cache)
        binance_usdt = balance["usdt"]
        send(
            f"🟢 BUY {qty} {symbol} at ${price:.2f} — Value: ${actual_cost:.2f} USDT | Remaining: ${binance_usdt:.2f} — {now}"
        )
        logger.info(
            "✅ BUY %s %s at $%.2f ($%.2f)", qty, symbol, price, actual_cost
        )
        return

    # Sell confirmation flow
    qty = decision["qty"]
    profit = decision.get("profit", 0.0)
    pnl = decision.get("pnl_pct", 0.0)
    trade_id = decision.get("trade_id")
    current_value = decision.get("current_value", qty * price)
    order_info = place_order(symbol, "sell", qty)
    logger.info("   ↳ order: %s", order_info)
    if trade_id is None:
        pos = db.get_open_positions().get(symbol)
        if pos:
            trade_id = pos.get("trade_id")
    if trade_id is not None:
        db.update_trade_pnl(trade_id, profit, profit, pnl)
    db.remove_position(symbol)

    if not LIVE_MODE:
        SIM_USDT_BALANCE += current_value
        client.get_asset_balance = lambda asset: {"free": str(SIM_USDT_BALANCE)}

    positions = db.get_open_positions()
    price_cache = {symbol: price}
    total = update_balance(balance, positions, price_cache)
    binance_usdt = balance["usdt"]

    reason = decision.get("reason")
    if reason == "take_profit":
        send(
            f"🎯 TARGET {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) | Balance: ${binance_usdt:.2f} — {now}"
        )
        logger.info(
            "🎯 TARGET %s at $%.2f | Profit: $%.2f USDT (+%.2f%%)",
            symbol,
            price,
            profit,
            pnl,
        )
    elif reason == "stop_loss":
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
    else:
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


def _handle_poll_answer(update: dict) -> None:
    poll_id = update.get("poll_id")
    if not poll_id:
        return
    symbol = PENDING_POLLS.get(poll_id)
    if not symbol:
        return
    option_ids = update.get("option_ids") or []
    if not option_ids:
        return
    approved = option_ids[0] == 0
    finalize_pending_decision(symbol, approved)

def poll_telegram_commands():
    """Listen for manual trade commands sent via Telegram."""
    global SIM_USDT_BALANCE
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {
                "timeout": 30,
                "offset": offset,
                "allowed_updates": ["message", "poll_answer", "poll"],
            }
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                if "poll_answer" in update:
                    _handle_poll_answer(update["poll_answer"])
                    continue
                poll = update.get("poll")
                if poll:
                    poll_id = poll.get("id")
                    if poll_id is not None:
                        symbol = PENDING_POLLS.get(poll_id) or PENDING_POLLS.get(
                            str(poll_id)
                        )
                        if symbol:
                            options = poll.get("options") or []
                            if options and (options[0].get("voter_count") or 0) > 0:
                                finalize_pending_decision(symbol, True)
                                continue
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                if str(chat_id) != str(TELEGRAM_CHAT_ID):
                    continue

                text = (msg.get("text") or "").strip()
                parts = text.split()
                if not parts:
                    continue
                cmd = parts[0].upper()

                if cmd in {"CONFIRM", "DECLINE"}:
                    if len(parts) < 2:
                        send("⚠️ Provide the symbol, e.g. 'CONFIRM BTCUSDT'.")
                        continue
                    symbol = parts[1].upper()
                    approved = cmd == "CONFIRM"
                    if not finalize_pending_decision(symbol, approved):
                        send(f"ℹ️ No pending decision for {symbol}")
                    continue

                if cmd == "BALANCE":
                    send_balance_breakdown()
                    continue

                if len(parts) < 2:
                    send_poll("Select action", ["BUY", "SELL"])
                    continue

                symbol = parts[1].upper()

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
                    
                    stop_distance = get_stop_distance(symbol, price)
                    qty, stop_loss, reason = calculate_position_size(
                        binance_usdt,
                        price,
                        RISK_PER_TRADE,
                        stop_distance,
                        MIN_TRADE_USDT,
                        MAX_TRADE_USDT,
                        fee_rate=FEE_RATE,
                    )

                    if qty <= 0:
                        send(f"⚠️ Unable to size position for {symbol}: {reason}")
                        continue

                    actual_cost = qty * price * (1 + FEE_RATE)
                    if actual_cost > binance_usdt:
                        send(f"⚠️ Insufficient balance for {symbol}")
                        continue
                    stop_distance = price - stop_loss if stop_loss is not None else stop_distance
                    take_profit = price + (
                        stop_distance
                        + price * FEE_RATE
                        + (price + stop_distance) * FEE_RATE
                    ) * RISK_REWARD

                    place_order(symbol, "buy", qty)
                    trade_id = db.log_trade(symbol, "BUY", qty, price)
                    db.upsert_position(
                        symbol,
                        qty,
                        price,
                        stop_loss,
                        take_profit,
                        trade_id,
                        price,
                        stop_distance,
                    )
                    
                    positions[symbol] = {
                        "qty": qty,
                        "entry": price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "trail_price": price,
                        "trade_id": trade_id,
                        "stop_distance": stop_distance,
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
                    if len(parts) != 3:
                        send("❓ SELL requires quantity")
                        continue
                    try:
                        qty = float(parts[2])
                    except ValueError:
                        send("❓ Quantity must be numeric")
                        continue

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
    except (FileNotFoundError, json.JSONDecodeError):
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

    
def format_balance_breakdown(summary: dict | None = None) -> str:
    """Format a human readable breakdown of liquid funds and positions."""

    if summary is None:
        summary = wallet_summary()

    start_bal = float(summary.get("start_balance", 0.0) or 0.0)
    current_bal = float(summary.get("current_balance", 0.0) or 0.0)
    positions = summary.get("positions") or []

    lines = [
        "💼 Balance breakdown:",
        f"• Starting balance: ${start_bal:.2f}",
        f"• Liquidity: ${current_bal:.2f}",
    ]

    if positions:
        lines.append("• Positions:")
        for pos in positions:
            symbol = pos.get("symbol", "?")
            qty = pos.get("qty", 0)
            entry = pos.get("entry")
            qty_str = f"{qty:g}" if isinstance(qty, (int, float)) else str(qty)
            if isinstance(entry, (int, float)):
                lines.append(f"  - {symbol}: {qty_str} @ ${float(entry):.2f}")
            else:
                lines.append(f"  - {symbol}: {qty_str}")
    else:
        lines.append("• Positions: none")

    return "\n".join(lines)


def send_balance_breakdown() -> None:
    """Fetch the wallet summary and deliver it to Telegram."""

    summary = wallet_summary()
    message = format_balance_breakdown(summary)
    send(message)

def maybe_send_balance_reminder(
    total: float,
    binance_usdt: float,
    now_str: str,
    price_cache: dict[str, float] | None,
) -> bool:
    """Send a balance reminder when the schedule or price action warrants it."""

    global LAST_BALANCE_REMINDER, PRICE_BASELINE

    cache_items = list(price_cache.items()) if price_cache else []
    for symbol, price in cache_items:
        if price and price > 0 and symbol not in PRICE_BASELINE:
            PRICE_BASELINE[symbol] = price

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    reason_type: str | None = None
    reason_detail: str | None = None

    if LAST_BALANCE_REMINDER is None:
        reason_type = "initial"
    else:
        if now_dt - LAST_BALANCE_REMINDER >= BALANCE_REMINDER_INTERVAL:
            reason_type = "scheduled"
        else:
            for symbol, price in cache_items:
                baseline = PRICE_BASELINE.get(symbol)
                if (
                    price
                    and price > 0
                    and baseline
                    and baseline > 0
                ):
                    change = abs(price - baseline) / baseline
                    if change >= BALANCE_PRICE_SHIFT_THRESHOLD:
                        reason_type = "major_shift"
                        reason_detail = f"{symbol} moved {change * 100:.2f}%"
                        break

    if reason_type is None:
        return False
        
    if is_within_quiet_hours(now_dt):
        logger.info("🔕 Balance reminder skipped during quiet hours (%s)", now_str)
        return False

    message = f"📊 Updated Balance: ${binance_usdt:.2f} (Total ${total:.2f}) — {now_str}"
    if reason_type == "major_shift" and reason_detail:
        message += f" — Triggered by {reason_detail} since last update"

    send(message)

    if reason_type == "major_shift" and reason_detail:
        logger.info("📊 Balance reminder triggered by %s", reason_detail)
    elif reason_type == "scheduled":
        logger.info("⏰ 3-Hour balance reminder sent")
    elif reason_type == "initial":
        logger.info("ℹ️ Initial balance reminder sent")

    LAST_BALANCE_REMINDER = now_dt
    for symbol, price in cache_items:
        if price and price > 0:
            PRICE_BASELINE[symbol] = price

    return True


# Get USDT balance from Binance
def get_usdt_balance():
    """Fetch available USDT balance for the configured trading mode"""
    global SIM_USDT_BALANCE

    def _get_spot_balance() -> float:
        bal = client.get_asset_balance(asset="USDT") or {}
        return float(bal.get("free", 0) or 0.0)

    def _get_margin_balance() -> float:
        account = client.get_margin_account() or {}
        assets = account.get("userAssets") or account.get("balances") or []
        for asset in assets:
            if asset.get("asset") == "USDT":
                free_value = asset.get("free") or asset.get("freeBalance") or 0.0
                return float(free_value or 0.0)
        return 0.0

    def _get():
        if TRADING_MODE == "margin":
            return _get_margin_balance()
        return _get_spot_balance()

    bal = call_with_retries(_get, name="Binance USDT balance")

    if LIVE_MODE:
        return bal if bal is not None else 0.0

    # In simulation mode we maintain an independent virtual balance so the bot
    # can operate without real funds.  When the exchange returns ``None`` or a
    # non-positive value (common with demo API keys), we keep the previously
    # tracked simulated balance instead of overwriting it with zero.  This keeps
    # the paper trading balance from being wiped out and allows trades to
    # proceed on subsequent cycles.
    if bal is None or bal <= 0:
        if SIM_USDT_BALANCE <= 0:
            SIM_USDT_BALANCE = START_BALANCE
        return SIM_USDT_BALANCE

    SIM_USDT_BALANCE = bal
    return SIM_USDT_BALANCE

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
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": qty,
        }
        if TRADING_MODE == "margin":
            if MARGIN_SIDE_EFFECT_TYPE:
                params["sideEffectType"] = MARGIN_SIDE_EFFECT_TYPE
            return client.create_margin_order(**params)
        return client.create_order(**params)
    if LIVE_MODE:
        return call_with_retries(_order, name=f"Binance order {symbol}")
    else:
        logger.info("[SIMULATED %s] %s %s %s", TRADING_MODE.upper(), side, qty, symbol)
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
        with sqlite3.connect("prices.db") as conn:
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
    except sqlite3.Error as exc:
        logger.error("Price save error: %s", exc)

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
                    pos.get("take_profit"),
                    pos["trade_id"],
                    pos.get("trail_price", pos["entry"]),
                    pos.get("stop_distance"),
                )
                db_positions[symbol]["qty"] = exch_qty
    for p in db_positions.values():
        if p.get("stop_distance") is None:
            stop = p.get("stop_loss")
            trail = p.get("trail_price", p.get("entry"))
            p["stop_distance"] = trail - stop if stop is not None else None
    return db_positions

def trade():
    global SIM_USDT_BALANCE
    positions = db.get_open_positions()
    for p in positions.values():
        if p.get("stop_distance") is None:
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

    buy_orders_this_cycle = 0

    for symbol in symbols:
        if (
            buy_orders_this_cycle >= MAX_ORDERS_PER_CYCLE
            and symbol not in positions
        ):
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
                
            updated = False
            if price > trail:
                trail = price
                pos["trail_price"] = trail
                stop = trail - stop_distance
                updated = True
            else:
                stop = pos.get("stop_loss")

            if (
                stop is not None
                and price - entry >= stop_distance
                and stop < entry
            ):
                stop = entry
                pos["stop_loss"] = stop
                updated = True
                take_profit = calculate_fee_adjusted_take_profit(
                    entry,
                    stop,
                    trail,
                    FEE_RATE,
                    RISK_REWARD,
                    MIN_EXIT_PNL_PCT,
                )
                pos["take_profit"] = take_profit
                db.upsert_position(
                    symbol,
                    qty,
                    entry,
                    stop,
                    take_profit,
                    pos.get("trade_id"),
                    trail,
                    pos.get("stop_distance"),
                )
                logger.info(
                    "🔒 %s stop-loss moved to break-even ($%.2f)",
                    symbol,
                    entry,
                )
                send(
                    f"🔒 {symbol} stop-loss moved to break-even at ${entry:.2f} — {now}"
                )
            elif updated:
                pos["stop_loss"] = stop
                take_profit = calculate_fee_adjusted_take_profit(
                    entry,
                    stop,
                    trail,
                    FEE_RATE,
                    RISK_REWARD,
                    MIN_EXIT_PNL_PCT,
                )
                pos["take_profit"] = take_profit
                db.upsert_position(
                    symbol,
                    qty,
                    entry,
                    stop,
                    take_profit,
                    pos.get("trade_id"),
                    trail,
                    pos.get("stop_distance"),
                )
                
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

            
            if stop is not None and price <= stop:
                decision = {
                    "action": "sell",
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "profit": profit,
                    "pnl_pct": pnl,
                    "trade_id": pos.get("trade_id"),
                    "current_value": current_value,
                    "reason": "stop_loss",
                    "timestamp": now,
                }
                if profit < 0:
                    question = (
                        f"Stop-loss hit for {symbol}. SELL {qty} at ${price:.2f} and realize ${profit:.2f} USDT ({pnl:.2f}%)?"
                    )
                    _store_pending_decision(decision, question)
                else:
                    _execute_decision(decision)
                    positions.pop(symbol, None)
                continue

            take_profit = pos.get("take_profit")
            if take_profit and price >= take_profit:
                decision = {
                    "action": "sell",
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "profit": profit,
                    "pnl_pct": pnl,
                    "trade_id": pos.get("trade_id"),
                    "current_value": current_value,
                    "reason": "take_profit",
                    "timestamp": now,
                }
                if profit < 0:
                    question = (
                        f"Take profit signal for {symbol} would lose ${abs(profit):.2f} USDT ({pnl:.2f}%). Confirm SELL {qty}?"
                    )
                    _store_pending_decision(decision, question)
                else:
                    _execute_decision(decision)
                    positions.pop(symbol, None)
                continue

            if strategy.should_sell(symbol, pos, price, headlines):
                decision = {
                    "action": "sell",
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "profit": profit,
                    "pnl_pct": pnl,
                    "trade_id": pos.get("trade_id"),
                    "current_value": current_value,
                    "reason": "strategy_exit",
                    "timestamp": now,
                }
                if profit < 0:
                    question = (
                        f"Strategy exit for {symbol} would realize ${profit:.2f} USDT ({pnl:.2f}%). SELL {qty}?"
                    )
                    _store_pending_decision(decision, question)
                else:
                    _execute_decision(decision)
                    positions.pop(symbol, None)
                continue

            continue

        # For new positions, defer decision to strategy
        if buy_orders_this_cycle >= MAX_ORDERS_PER_CYCLE:
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


        take_profit = calculate_fee_adjusted_take_profit(
            price,
            stop_loss,
            price,
            FEE_RATE,
            RISK_REWARD,
            MIN_EXIT_PNL_PCT,
        )
        decision = {
            "action": "buy",
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stop_distance": price - stop_loss if stop_loss is not None else stop_distance,
            "actual_cost": actual_cost,
            "timestamp": now,
        }

        _execute_decision(decision)
        positions = db.get_open_positions()
        binance_usdt = get_usdt_balance()
        balance["usdt"] = binance_usdt
        buy_orders_this_cycle += 1
        continue

    # Balance update
    total = update_balance(balance, positions, price_cache)
    binance_usdt = balance["usdt"]
    maybe_send_balance_reminder(total, binance_usdt, now, price_cache)

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
