import os
import threading
import logging
from typing import Dict, List, Optional

from binance import ThreadedWebsocketManager

logger = logging.getLogger(__name__)

# Thread-safe cache for latest prices
latest_prices: Dict[str, float] = {}
_prices_lock = threading.Lock()

# Websocket manager and control variables
_twm: Optional[ThreadedWebsocketManager] = None
_symbols: List[str] = []
_monitor_thread: Optional[threading.Thread] = None
_monitor_stop = threading.Event()


def _handle_ticker(msg: dict):
    """Process incoming ticker messages and update the price cache."""
    try:
        symbol = msg.get("s")
        price = float(msg.get("c"))
        with _prices_lock:
            latest_prices[symbol] = price
    except Exception as exc:
        logger.exception("ticker processing error: %s", exc)


def _start_manager() -> None:
    """Start the websocket manager and subscribe to symbol streams."""
    global _twm
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_SECRET_KEY")
    _twm = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret)
    _twm.start()
    for sym in _symbols:
        _twm.start_symbol_ticker_socket(callback=_handle_ticker, symbol=sym)


def _monitor() -> None:
    """Monitor websocket connection and restart if needed."""
    # The monitor loop wakes up periodically to check whether the websocket
    # manager is still alive.  Using ``Event.wait`` lets us react immediately to
    # shutdown requests instead of being stuck in ``time.sleep`` for the full
    # interval, which previously delayed ``stop_stream`` for up to 30 seconds.
    while not _monitor_stop.wait(30):
        if _twm and not _twm.is_alive():
            try:
                _twm.stop()
            except Exception:
                pass
            _start_manager()


def start_stream(trading_pairs: List[str]) -> None:
    """Begin streaming ticker prices for the given trading pairs."""
    global _symbols, _monitor_thread
    # Copy the provided list so later mutations by the caller do not
    # concurrently alter the monitor thread's subscription list.
    _symbols = list(trading_pairs)
    _monitor_stop.clear()
    _start_manager()
    if not _monitor_thread or not _monitor_thread.is_alive():
        _monitor_thread = threading.Thread(target=_monitor, daemon=True)
        _monitor_thread.start()

def stop_stream() -> None:
    """Stop streaming prices and reset internal state."""
    global _twm, _symbols, _monitor_thread
    _monitor_stop.set()
    if _twm:
        try:
            _twm.stop()
        except Exception:
            pass
        _twm = None
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=5)
        if _monitor_thread.is_alive():
            logger.warning("monitor thread did not shut down cleanly")
    _monitor_thread = None
    _symbols = []
    with _prices_lock:
        latest_prices.clear()
    _monitor_stop.clear()

def get_latest_price(symbol: str) -> Optional[float]:
    """Return the most recently cached price for ``symbol`` or ``None``."""
    with _prices_lock:
        return latest_prices.get(symbol)
