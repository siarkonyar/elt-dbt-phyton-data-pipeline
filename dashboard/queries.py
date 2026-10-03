"""Every SQL statement the dashboard runs.

Kept out of app.py so they can be imported without starting Streamlit.
app.py is a script, not a library: importing it sets the page config, opens a
database engine and renders the page. This module has no side effects, so
tests can import it and assert against the queries the dashboard really runs.
"""

from sqlalchemy import text

# The trade feed gives us a price and nothing else, so open/high/low are
# derived from the trades we stored rather than handed over by the API.
# now() is UTC in the container, and the whole US session lives inside one
# UTC day, so date_trunc('day') is a safe boundary here.
LATEST_SQL = text(
    """
    WITH today AS (
        SELECT symbol, trade_ts, price
          FROM raw_trades
         WHERE trade_ts >= date_trunc('day', now())
    ),
    stats AS (
        SELECT symbol, min(price) AS day_low, max(price) AS day_high,
               count(*) AS trades_today
          FROM today
         GROUP BY symbol
    ),
    opens AS (
        SELECT DISTINCT ON (symbol) symbol, price AS day_open
          FROM today
         ORDER BY symbol, trade_ts
    ),
    latest AS (
        SELECT DISTINCT ON (symbol) symbol, trade_ts, price, volume
          FROM raw_trades
         ORDER BY symbol, trade_ts DESC
    )
    SELECT latest.symbol, latest.trade_ts, latest.price, latest.volume,
           opens.day_open, stats.day_high, stats.day_low, stats.trades_today
      FROM latest
      LEFT JOIN opens ON opens.symbol = latest.symbol
      LEFT JOIN stats ON stats.symbol = latest.symbol
     ORDER BY latest.symbol
    """
)

# Full OHLC per minute, straight off the rollup. Deriving these from raw ticks
# meant a DISTINCT ON over every trade in the window; this is an index range
# scan over one row per symbol per minute. A candle needs all four prices -
# selecting close alone can only ever draw a line.
CANDLES_SQL = text(
    """
    SELECT symbol, minute AS at, open, high, low, close
      FROM candles
     WHERE minute >= now() - make_interval(hours => :hours)
     ORDER BY symbol, minute
    """
)

SESSIONS_SQL = text(
    """
    SELECT session_id, connected_at, disconnected_at, symbols,
           trades_received, rows_written, last_message_at, last_trade_at,
           reconnects, market_open, market_session, status, error_message
      FROM stream_sessions
     ORDER BY session_id DESC
     LIMIT 20
    """
)

ROLLUP_RUNS_SQL = text(
    """
    SELECT run_id, started_at, finished_at, window_start, window_end,
           trades_read, minutes_written, status, error_message
      FROM rollup_runs
     ORDER BY run_id DESC
     LIMIT 20
    """
)

# reltuples is an autovacuum estimate, so it is instant even on a huge table.
# count(*) would scan every row on every refresh.
STORAGE_SQL = text(
    """
    SELECT pg_size_pretty(pg_total_relation_size('raw_trades')) AS on_disk,
           (SELECT reltuples::bigint FROM pg_class WHERE relname = 'raw_trades')
               AS approx_rows
    """
)

# max(minute) rides the candles_idx index and reltuples is an estimate, so
# neither of these gets slower as the table grows.
CANDLE_STATUS_SQL = text(
    """
    SELECT (SELECT max(minute) FROM candles) AS newest_minute,
           (SELECT reltuples::bigint FROM pg_class WHERE relname = 'candles')
               AS approx_candles
    """
)
