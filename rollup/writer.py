from sqlalchemy import text

UPSERT_CANDLES_SQL = text(
    """
    INSERT INTO trades_1m
        (symbol, minute, open, high, low, close, volume, trade_count, updated_at)
    VALUES
        (:symbol, :minute, :open, :high, :low, :close, :volume, :trade_count, now())
    ON CONFLICT (symbol, minute) DO UPDATE
       SET open        = EXCLUDED.open,
           high        = EXCLUDED.high,
           low         = EXCLUDED.low,
           close       = EXCLUDED.close,
           volume      = EXCLUDED.volume,
           trade_count = EXCLUDED.trade_count,
           updated_at  = now()
    """
)


def _records(candles):
    """psycopg2 cannot adapt numpy scalars, so hand it native Python types."""
    return [
        {
            "symbol": str(row.symbol),
            "minute": row.minute.to_pydatetime(),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
            "trade_count": int(row.trade_count),
        }
        for row in candles.itertuples(index=False)
    ]


def upsert_candles(connection, candles):
    """One round trip for the whole batch. Returns rows written."""
    if candles.empty:
        return 0

    connection.execute(UPSERT_CANDLES_SQL, _records(candles))
    return len(candles)


START_RUN_SQL = text(
    """
    INSERT INTO rollup_runs (started_at, window_start, window_end, status)
    VALUES (now(), :window_start, :window_end, 'running')
    RETURNING run_id
    """
)


def start_run(connection, window_start, window_end):
    return connection.execute(
        START_RUN_SQL,
        {"window_start": window_start, "window_end": window_end},
    ).scalar_one()


FINISH_RUN_SQL = text(
    """
    UPDATE rollup_runs
       SET finished_at     = now(),
           trades_read     = :trades_read,
           minutes_written = :minutes_written,
           status          = :status,
           error_message   = :error_message
     WHERE run_id = :run_id
    """
)


def finish_run(
    connection,
    run_id,
    status,
    trades_read=0,
    minutes_written=0,
    error_message=None,
):
    """status is 'ok' or 'failed'."""
    connection.execute(
        FINISH_RUN_SQL,
        {
            "run_id": run_id,
            "status": status,
            "trades_read": trades_read,
            "minutes_written": minutes_written,
            "error_message": error_message,
        },
    )