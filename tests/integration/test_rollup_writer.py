from datetime import datetime, timezone

import pandas as pd
from candles import build_candles
from sqlalchemy import text

BASE_MINUTE = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")
WINDOW_END = datetime(2024, 1, 1, 12, 10, tzinfo=timezone.utc)
WINDOW_START = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

CANDLE_COLUMNS = [
    "symbol", "minute", "open", "high", "low", "close", "volume", "trade_count",
]

STORED_CANDLES_SQL = text(
    """
    SELECT symbol, minute, open, high, low, close, volume, trade_count
      FROM candles
     ORDER BY symbol, minute
    """
)


def candles_frame(rows):
    return pd.DataFrame(rows, columns=CANDLE_COLUMNS)


def one_candle(symbol="NVDA", minute=BASE_MINUTE, close=104.0, volume=10.0, count=4):
    return candles_frame([(symbol, minute, 101.0, 108.0, 95.0, close, volume, count)])


def read_run(connection, run_id):
    return connection.execute(
        text("SELECT * FROM rollup_runs WHERE run_id = :id"), {"id": run_id}
    ).one()


# --- upsert_candles ---

def test_upsert_inserts_a_new_candle(rollup_tables, rollup_writer):
    written = rollup_writer.upsert_candles(rollup_tables, one_candle())

    assert written == 1
    row = rollup_tables.execute(STORED_CANDLES_SQL).one()
    assert row.symbol == "NVDA"
    assert float(row.open) == 101.0
    assert float(row.high) == 108.0
    assert float(row.low) == 95.0
    assert float(row.close) == 104.0
    assert row.trade_count == 4


def test_upsert_with_an_empty_frame_writes_nothing(rollup_tables, rollup_writer):
    written = rollup_writer.upsert_candles(rollup_tables, candles_frame([]))

    assert written == 0
    stored = rollup_tables.execute(text("SELECT count(*) FROM candles")).scalar_one()
    assert stored == 0


def test_upsert_replaces_a_minute_it_has_already_written(rollup_tables, rollup_writer):
    # The partial candle, written while the minute was still filling.
    rollup_writer.upsert_candles(rollup_tables, one_candle(close=104.0, volume=10.0, count=4))

    # The finished candle, after the late trades arrived.
    rollup_writer.upsert_candles(rollup_tables, one_candle(close=107.0, volume=18.0, count=9))

    rows = rollup_tables.execute(STORED_CANDLES_SQL).all()

    assert len(rows) == 1
    assert float(rows[0].close) == 107.0
    assert float(rows[0].volume) == 18.0
    assert rows[0].trade_count == 9


def test_running_the_same_batch_twice_changes_nothing(rollup_tables, rollup_writer):
    candles = one_candle()

    rollup_writer.upsert_candles(rollup_tables, candles)
    first = rollup_tables.execute(STORED_CANDLES_SQL).all()

    rollup_writer.upsert_candles(rollup_tables, candles)
    second = rollup_tables.execute(STORED_CANDLES_SQL).all()

    assert first == second


def test_different_minutes_live_side_by_side(rollup_tables, rollup_writer):
    rollup_writer.upsert_candles(rollup_tables, one_candle(minute=BASE_MINUTE))
    rollup_writer.upsert_candles(
        rollup_tables, one_candle(minute=BASE_MINUTE + pd.Timedelta(minutes=1))
    )

    stored = rollup_tables.execute(text("SELECT count(*) FROM candles")).scalar_one()
    assert stored == 2


def test_different_symbols_live_side_by_side(rollup_tables, rollup_writer):
    rollup_writer.upsert_candles(rollup_tables, one_candle(symbol="NVDA"))
    rollup_writer.upsert_candles(rollup_tables, one_candle(symbol="AMZN"))

    stored = rollup_tables.execute(text("SELECT count(*) FROM candles")).scalar_one()
    assert stored == 2


def test_candles_built_by_build_candles_can_actually_be_written(rollup_tables, rollup_writer):
    # build_candles returns numpy.float64 and numpy.int64. psycopg2 has no
    # adapter for those - this fails with "can't adapt type 'numpy.float64'"
    # the moment _records stops converting to native Python types.
    trades = pd.DataFrame({
        "symbol": ["NVDA", "NVDA"],
        "trade_ts": [
            pd.Timestamp("2024-01-01 12:00:10", tz="UTC"),
            pd.Timestamp("2024-01-01 12:00:20", tz="UTC"),
        ],
        "price": [100.0, 105.0],
        "volume": [1.0, 2.0],
    })

    written = rollup_writer.upsert_candles(rollup_tables, build_candles(trades))

    assert written == 1
    row = rollup_tables.execute(STORED_CANDLES_SQL).one()
    assert float(row.open) == 100.0
    assert float(row.close) == 105.0
    assert row.trade_count == 2


# --- run logging ---

def test_start_run_returns_a_usable_id(rollup_tables, rollup_writer):
    run_id = rollup_writer.start_run(rollup_tables, WINDOW_START, WINDOW_END)

    assert isinstance(run_id, int)


def test_a_new_run_is_marked_running_with_no_finish_time(rollup_tables, rollup_writer):
    run_id = rollup_writer.start_run(rollup_tables, WINDOW_START, WINDOW_END)

    row = read_run(rollup_tables, run_id)

    assert row.status == "running"
    assert row.finished_at is None
    assert row.window_start == WINDOW_START
    assert row.window_end == WINDOW_END


def test_a_finished_run_records_its_counts(rollup_tables, rollup_writer):
    run_id = rollup_writer.start_run(rollup_tables, WINDOW_START, WINDOW_END)

    rollup_writer.finish_run(
        rollup_tables, run_id, "ok", trades_read=120, minutes_written=8
    )

    row = read_run(rollup_tables, run_id)

    assert row.status == "ok"
    assert row.trades_read == 120
    assert row.minutes_written == 8
    assert row.finished_at is not None
    assert row.error_message is None


def test_a_failed_run_records_the_error(rollup_tables, rollup_writer):
    run_id = rollup_writer.start_run(rollup_tables, WINDOW_START, WINDOW_END)

    rollup_writer.finish_run(
        rollup_tables, run_id, "failed", error_message="ProgrammingError: boom"
    )

    row = read_run(rollup_tables, run_id)

    assert row.status == "failed"
    assert row.error_message == "ProgrammingError: boom"
    assert row.minutes_written == 0