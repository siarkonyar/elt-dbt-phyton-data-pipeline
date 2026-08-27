import json
from dataclasses import dataclass
from datetime import datetime, timezone

import websocket

SUBSCRIBE = "subscribe"
TRADE = "trade"
PING = "ping"
ERROR = "error"

@dataclass(frozen=True)
class Trade:
    symbol: str
    trade_ts: datetime
    price: float
    volume: float
    conditions: str

def parse_message(raw):
    """Finnhub JSON -> (message type, tuple of Trades). Never raises."""
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return ERROR, ()

    message_type = message.get("type")

    if message_type != TRADE:
        return message_type, ()

    return TRADE, tuple(
        Trade(
            symbol=item["s"],
            trade_ts=datetime.fromtimestamp(item["t"] / 1000, tz=timezone.utc),
            price=float(item["p"]),
            volume=float(item.get("v") or 0),
            conditions=",".join(str(code) for code in item.get("c") or ()),
        )
        for item in message.get("data") or ()
    )

class FinnhubSocket:
    """Owns one connection. Parses messages onto a queue and nothing else."""

    def __init__(self, endpoint, symbols, queue, on_event):
        self.endpoint = endpoint
        self.symbols = symbols
        self.queue = queue
        self.on_event = on_event

    def _on_open(self, socket):
        for symbol in self.symbols:
            socket.send(json.dumps({"type": SUBSCRIBE, "symbol": symbol}))
        self.on_event("open", None)

    def _on_message(self, socket, raw):
        message_type, trades = parse_message(raw)

        for trade in trades:
            self.queue.put(trade)

        self.on_event(message_type, len(trades))

    def _on_error(self, socket, error):
        self.on_event("failed", f"{type(error).__name__}: {error}")

    def _on_close(self, socket, status_code, message):
        self.on_event("closed", status_code)

    def run_forever(self):
        """Blocks until the connection drops. Returns so the caller can retry."""
        socket = websocket.WebSocketApp(
            self.endpoint,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        socket.run_forever(ping_interval=30, ping_timeout=10)