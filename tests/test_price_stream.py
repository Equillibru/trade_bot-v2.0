import price_stream


class DummyTWM:
    def __init__(self, *args, **kwargs):
        self.callbacks = []
        self._running = False

    def start(self):
        self._running = True

    def is_alive(self):
        return self._running

    def stop(self):
        self._running = False

    def start_symbol_ticker_socket(self, callback, symbol):
        self.callbacks.append(callback)


def test_price_cache_updates(monkeypatch):
    dummy = DummyTWM()
    monkeypatch.setattr(price_stream, "ThreadedWebsocketManager", lambda **kw: dummy)
    # prevent long-running monitor thread
    monkeypatch.setattr(price_stream, "_monitor", lambda: None)

    price_stream.latest_prices.clear()
    price_stream.start_stream(["BTCUSDT"])

    try:
        assert dummy.callbacks, "No callback registered"
        msg = {"s": "BTCUSDT", "c": "123.45"}
        for cb in dummy.callbacks:
            cb(msg)

        assert price_stream.get_latest_price("BTCUSDT") == 123.45
    finally:
        price_stream.stop_stream()
