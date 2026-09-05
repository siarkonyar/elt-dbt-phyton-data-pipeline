import queue
import sys
import threading
import time
from datetime import datetime, timezone

from backoff import ExponentialBackoff
from buffer import drain
from config import ConfigError, load_config
from db import apply_schema, get_engine
from market_status import build_session, fetch_market_status
from socket_client import TRADE, FinnhubSocket
from writer import finish_session, heartbeat, insert_trades, start_session

LOG_INTERVAL_SECONDS = 30

class SocketEvents:
    """Written by the socket thread, read by the flush loop."""

    def __init__(self):
        self.last_message_at = None
        self.last_trade_at = None
        self.trades_seen = 0
        self.error = None
        self.closed = threading.Event()#this is a flag like a boolean

    def record(self, event_type, detail):
        """This is the on_event callback FinnhubSocket calls."""
        self.last_message_at = datetime.now(timezone.utc)

        if event_type == TRADE and detail:
            self.last_trade_at = self.last_message_at
            self.trades_seen += detail
        elif event_type == "failed":
            self.error = detail
        elif event_type == "closed":
            self.closed.set()

def safe_market_status(config, http):
    """Returns None on failure. Never stops the stream."""
    try:
        return fetch_market_status(http, config.base_url, config.timeout_seconds)
    except Exception as error:
        print(
            f"market status unavailable: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return None


def flush_loop(config, engine, http, events, session_id, trades_queue):
    """Writes once a second until the socket closes. Runs on the main thread."""
    reported = 0
    status = None
    next_status_at = 0.0
    next_log_at = 0.0

    while True:
        time.sleep(config.flush_interval_seconds)

        trades = drain(trades_queue, config.flush_max_rows)

        if time.monotonic() >= next_status_at:
            status = safe_market_status(config, http) or status
            next_status_at = time.monotonic() + config.market_status_interval_seconds

        seen = events.trades_seen

        try:
            with engine.begin() as connection:
                rows = insert_trades(connection, trades)#this line writes the trades
                heartbeat(
                    connection,
                    session_id,
                    trades=seen - reported,
                    rows=rows,
                    last_message_at=events.last_message_at,
                    last_trade_at=events.last_trade_at,
                    market_open=None if status is None else status.is_open,
                    market_session=None if status is None else status.session,
                )
            reported = seen
        except Exception as error:
            print(f"write failed: {type(error).__name__}: {error}", file=sys.stderr)

        if time.monotonic() >= next_log_at:
            print(
                f"{seen} trades seen | queue={trades_queue.qsize()} | "
                f"market={'open' if status and status.is_open else 'closed'}"
            )
            next_log_at = time.monotonic() + LOG_INTERVAL_SECONDS

        if events.closed.is_set():
            break

def run_once(config, engine, http, reconnects):
    """Connects, streams until the socket drops, returns what happened."""
    trades_queue = queue.Queue()
    events = SocketEvents()
    socket = FinnhubSocket(
        config.ws_endpoint, config.symbols, trades_queue, events.record
    )

    with engine.begin() as connection:
        session_id = start_session(connection, config.symbols, reconnects)

    thread = threading.Thread(target=socket.run_forever, daemon=True)
    thread.start()

    try:
        flush_loop(config, engine, http, events, session_id, trades_queue)
    finally:
        with engine.begin() as connection:
            finish_session(
                connection,
                session_id,
                "failed" if events.error else "closed",
                events.error,
            )

    return events

def main():
    config = load_config()
    engine = get_engine()

    with engine.begin() as connection:
        apply_schema(connection)

    http = build_session(config.api_key)
    backoff = ExponentialBackoff(
        config.reconnect_min_seconds, config.reconnect_max_seconds
    )
    reconnects = 0

    print(f"streaming {', '.join(config.symbols)} from {config.ws_url}")

    while True:
        events = run_once(config, engine, http, reconnects)

        if events.last_message_at is not None:
            backoff = backoff.reset()

        delay, backoff = backoff.next_delay()
        reconnects += 1
        print(f"disconnected — reconnecting in {delay:.1f}s", file=sys.stderr)
        time.sleep(delay)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as error:
        print(f"Configuration problem: {error}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("stopped")