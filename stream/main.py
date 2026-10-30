import queue
import sys
import threading
import time
from datetime import UTC, datetime

from alerts import find_triggered
from backoff import ExponentialBackoff
from buffer import drain
from config import ConfigError, load_config
from db import apply_schema, get_engine, read_day_stats, read_pending_alerts
from live_prices import connect, merge, read_live_prices, write_live_prices
from market_status import build_session, fetch_market_status
from notify import connect_broker, queue_alert_emails
from socket_client import TRADE, FinnhubSocket
from writer import (
    finish_session,
    heartbeat,
    insert_trades,
    mark_triggered,
    start_session,
)

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
        self.last_message_at = datetime.now(UTC)

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


def check_alerts(engine, trades):
    if not trades:
        return []

    try:
        with engine.begin() as connection:
            fired = find_triggered(read_pending_alerts(connection), trades)
            mark_triggered(connection, fired)
    except Exception as error:
        print(f"alert check failed: {type(error).__name__}: {error}", file=sys.stderr)
        return []

    return [alert["alert_id"] for alert in fired]


def load_live_prices(client, engine, trades, reseed):
    """Each batch symbol's stored values, seeded from Postgres wherever Redis
    has nothing for today. Runs before the insert, so a seed never already
    holds this batch. None means this flush skips Redis."""
    if not trades:
        return {}

    symbols = sorted({trade.symbol for trade in trades})
    day = max(trade.trade_ts for trade in trades).date()

    try:
        stored = {} if reseed else read_live_prices(client, symbols)
        stale = [s for s in symbols if stored.get(s, {}).get("day") != day]
        if not stale:
            return stored

        with engine.begin() as connection:
            seeded = read_day_stats(connection, stale, day)
        return {**stored, **seeded}
    except Exception as error:
        print(
            f"live prices not loaded: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return None


def save_live_prices(client, stored, trades):
    """True once Redis holds this batch. Called only after the insert worked,
    so Redis never counts a trade that Postgres does not have."""
    symbols = {trade.symbol for trade in trades}

    try:
        write_live_prices(client, {
            symbol: merge(stored[symbol], [t for t in trades if t.symbol == symbol])
            for symbol in symbols
        })
        return True
    except Exception as error:
        print(
            f"live prices not saved: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return False


def flush_loop(
        config,
        engine,
        redis_client,
        http, events,
        session_id,
        trades_queue,
        broker
    ):
    """Writes once a second until the socket closes. Runs on the main thread."""
    reported = 0
    status = None
    next_status_at = 0.0
    next_log_at = 0.0
    # A crash between an insert and its Redis write would leave a hash short
    # of that batch, so every loop starts by rebuilding from Postgres.
    needs_reseed = True

    while True:
        time.sleep(config.flush_interval_seconds)

        trades = drain(trades_queue, config.flush_max_rows)
        stored = load_live_prices(redis_client, engine, trades, needs_reseed)

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
        else:
            # An empty flush changes nothing, so it must not clear the flag.
            if trades:
                needs_reseed = stored is None or not save_live_prices(
                    redis_client, stored, trades
                )

        fired = check_alerts(engine, trades)

        if fired:
            print(f"{len(fired)} alerts triggered")
            queue_alert_emails(broker, fired)

        if time.monotonic() >= next_log_at:
            print(
                f"{seen} trades seen | queue={trades_queue.qsize()} | "
                f"market={'open' if status and status.is_open else 'closed'}"
            )
            next_log_at = time.monotonic() + LOG_INTERVAL_SECONDS

        if events.closed.is_set():
            break

def run_once(config, engine, redis_client, http, reconnects, broker):
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
        flush_loop(
            config,
            engine,
            redis_client,
            http, events,
            session_id,
            trades_queue,
            broker
        )
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
    redis_client = connect(config.redis_url)
    broker = connect_broker(config.celery_broker_url)
    backoff = ExponentialBackoff(
        config.reconnect_min_seconds, config.reconnect_max_seconds
    )
    reconnects = 0

    print(f"streaming {', '.join(config.symbols)} from {config.ws_url}")

    while True:
        events = run_once(config, engine, redis_client, http, reconnects, broker)

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
