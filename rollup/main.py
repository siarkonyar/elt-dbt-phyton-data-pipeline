import sys
import time
from datetime import UTC, datetime, timedelta

from alerts import find_triggered, latest_closes
from candles import build_candles
from config import ConfigError, load_config
from db import apply_schema, get_engine, read_pending_alerts, read_recent_trades
from writer import finish_run, mark_triggered, start_run, upsert_candles


def run_once(config, engine):
    """One pass over the trailing window.

    Returns (candles written, alerts fired) - the same shape on the failure
    path, so the caller can always unpack it.
    """
    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(minutes=config.window_minutes)

    with engine.begin() as connection:
        run_id = start_run(connection, window_start, window_end)

    try:
        with engine.begin() as connection:
            trades = read_recent_trades(connection, window_start, config.max_rows)
            candles = build_candles(trades)
            written = upsert_candles(connection, candles)

            prices = latest_closes(candles)
            alerts = read_pending_alerts(connection)

            triggered_alerts = find_triggered(alerts, prices)

            triggered = mark_triggered(connection, triggered_alerts)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        print(f"rollup failed: {message}", file=sys.stderr)

        with engine.begin() as connection:
            finish_run(connection, run_id, "failed", error_message=message)

        return 0, 0

    with engine.begin() as connection:
        finish_run(connection, run_id, "ok", len(trades), written)

    return written, triggered


def main():
    config = load_config()
    engine = get_engine()

    with engine.begin() as connection:
        apply_schema(connection)

    print(
        f"rolling up a {config.window_minutes}-minute window "
        f"every {config.interval_seconds:.0f}s"
    )

    while True:
        try:
            written, triggered = run_once(config, engine)

            print(f"{written} candles written")
            print(f"{triggered} alerts triggered")
        except Exception as error:
            # run_once handles its own failures; reaching here means the
            # database itself went away. Log it and keep the loop alive.
            print(
                f"rollup run failed: {type(error).__name__}: {error}",
                file=sys.stderr,
            )

        time.sleep(config.interval_seconds)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as error:
        print(f"Configuration problem: {error}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("stopped")
