import sys
import time
from datetime import datetime, timedelta, timezone

from candles import build_candles
from config import ConfigError, load_config
from db import apply_schema, get_engine, read_recent_trades
from writer import finish_run, start_run, upsert_candles


def run_once(config, engine):
    """One pass over the trailing window. Returns candles written."""
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(minutes=config.window_minutes)

    with engine.begin() as connection:
        run_id = start_run(connection, window_start, window_end)

    try:
        with engine.begin() as connection:
            trades = read_recent_trades(connection, window_start, config.max_rows)
            candles = build_candles(trades)
            written = upsert_candles(connection, candles)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        print(f"rollup failed: {message}", file=sys.stderr)

        with engine.begin() as connection:
            finish_run(connection, run_id, "failed", error_message=message)

        return 0

    with engine.begin() as connection:
        finish_run(connection, run_id, "ok", len(trades), written)

    return written


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
            written = run_once(config, engine)
            print(f"{written} candles written")
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