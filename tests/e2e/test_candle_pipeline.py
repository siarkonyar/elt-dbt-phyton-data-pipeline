from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text

HISTORY_HOURS = 24
MINUTES_BACK = 2

INSERT_TRADE_SQL = text(
    """
    INSERT INTO raw_trades (symbol, trade_ts, price, volume)
    VALUES (:symbol, :trade_ts, :price, :volume)
    """
)

def base_minute():
    now = datetime.now(timezone.utc)
    return now.replace(second=0, microsecond=0) - timedelta(minutes=MINUTES_BACK)

def insert_trades(engine, rows):
    """Committed for real - run_once opens its own connection, and rows still
    sitting in an uncommitted transaction would be invisible to it."""
    with engine.begin() as connection:
        connection.execute(
            INSERT_TRADE_SQL,
            [
                {"symbol": symbol, "trade_ts": at, "price": price, "volume": volume}
                for symbol, at, price, volume in rows
            ],
        )

def one_busy_minute(minute):
    """Four NVDA trades in one minute, plus a lone AMZN trade.

    Deliberately not in price order: open and close mean first and last by
    TIME, and a sorted list could not tell the difference.
    """
    return [
        ("NVDA", minute + timedelta(seconds=10), 100.0, 1.0),
        ("NVDA", minute + timedelta(seconds=20), 108.0, 2.0),
        ("NVDA", minute + timedelta(seconds=30), 95.0, 3.0),
        ("NVDA", minute + timedelta(seconds=40), 104.0, 4.0),
        ("AMZN", minute + timedelta(seconds=15), 200.0, 5.0),
    ]

def read_candles(engine, queries):
    return pd.read_sql(
        queries.CANDLES_SQL, engine, params={"hours": HISTORY_HOURS}
    )

def test_a_trade_becomes_a_candle_the_dashboard_can_find(
    e2e_db, rollup_main, rollup_config, dashboard_queries
):
    insert_trades(e2e_db, one_busy_minute(base_minute()))

    written = rollup_main.run_once(rollup_config.load_config({}), e2e_db)

    assert written == 2

    candles = read_candles(e2e_db, dashboard_queries)
    assert list(candles["symbol"]) == ["AMZN", "NVDA"]

    nvda = candles[candles["symbol"] == "NVDA"].iloc[0]
    assert float(nvda["open"]) == 100.0    # first by time, not lowest
    assert float(nvda["high"]) == 108.0
    assert float(nvda["low"]) == 95.0
    assert float(nvda["close"]) == 104.0

def test_the_run_is_recorded_for_the_dashboard(
    e2e_db, rollup_main, rollup_config, dashboard_queries
):
    insert_trades(e2e_db, one_busy_minute(base_minute()))

    rollup_main.run_once(rollup_config.load_config({}), e2e_db)

    runs = pd.read_sql(dashboard_queries.ROLLUP_RUNS_SQL, e2e_db)

    assert len(runs) == 1
    run = runs.iloc[0]
    assert run["status"] == "ok"
    assert run["trades_read"] == 5
    assert run["minutes_written"] == 2
    assert pd.isna(run["error_message"])

def test_a_late_trade_corrects_its_candle_instead_of_duplicating(
    e2e_db, rollup_main, rollup_config, dashboard_queries
):
    config = rollup_config.load_config({})
    minute = base_minute()

    insert_trades(e2e_db, [("NVDA", minute + timedelta(seconds=10), 100.0, 1.0)])
    rollup_main.run_once(config, e2e_db)

    # The late trade, in a minute that already has a candle. This is the
    # whole reason the writer upserts instead of inserting.
    insert_trades(e2e_db, [("NVDA", minute + timedelta(seconds=50), 130.0, 2.0)])
    rollup_main.run_once(config, e2e_db)

    candles = read_candles(e2e_db, dashboard_queries)

    assert len(candles) == 1               # corrected, not duplicated
    assert float(candles.iloc[0]["close"]) == 130.0
    assert float(candles.iloc[0]["high"]) == 130.0

    runs = pd.read_sql(dashboard_queries.ROLLUP_RUNS_SQL, e2e_db)
    assert len(runs) == 2