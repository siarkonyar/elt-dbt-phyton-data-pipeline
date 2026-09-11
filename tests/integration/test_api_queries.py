from datetime import UTC, datetime, timedelta

from sqlalchemy import text

HISTORY_HOURS = 24
MINUTES_BACK = 2

INSERT_CANDLES_SQL = text(
    """
    INSERT INTO candles (symbol, minute, open, high, low, close, volume, trade_count)
    VALUES (:symbol, :minute, :open, :high, :low, :close, :volume, :trade_count)
    """
)

def base_minute():
    now = datetime.now(UTC)
    return now.replace(second=0, microsecond=0) - timedelta(minutes=MINUTES_BACK)

def insert_candles(engine, rows):
    with engine.begin() as connection:
        connection.execute(
            INSERT_CANDLES_SQL,
            [
                {
                    "symbol": symbol, "minute": minute, "open": open_,
                    "high": high, "low": low, "close": close,
                    "volume": volume, "trade_count": trade_count
                }
                for symbol, minute, open_, high, low, close, volume, trade_count in rows
            ]
        )

def test_returns_the_candles_for_the_requested_symbol(e2e_db, api_db):
    minute = base_minute()
    insert_candles(e2e_db, [
        ("NVDA", minute, 100.0, 108.0, 95.0, 104.0, 10.0, 4),
        ("AMZN", minute, 200.0, 205.0, 198.0, 201.0, 5.0, 1),
    ])

    rows = api_db.read_candles(e2e_db, "NVDA", 1)
    assert all(row.symbol=="NVDA" for row in rows)
    assert len(rows) == 1

def test_ignores_the_other_symbols(e2e_db, api_db):
    minute= base_minute()
    insert_candles(e2e_db, [
        ("NVDA", minute - timedelta(minutes=1), 101.0, 103.0, 99.0, 102.0, 3.0, 2),
        ("NVDA", minute - timedelta(minutes=3), 100.0, 108.0, 95.0, 104.0, 10.0, 4),
        ("NVDA", minute - timedelta(minutes=2), 104.0, 106.0, 103.0, 105.0, 6.0, 3),
        ("AMZN", minute, 200.0, 205.0, 198.0, 201.0, 5.0, 1),
    ])

    rows = api_db.read_candles(e2e_db, "NVDA", 1)
    assert "AMZN" not in {row.symbol for row in rows}
    assert all(row.symbol == "NVDA" for row in rows)
    assert len(rows) == 3

def test_a_symbol_with_no_candles_returns_no_rows(e2e_db, api_db):
    minute= base_minute()
    insert_candles(e2e_db, [
        ("NVDA", minute - timedelta(minutes=1), 101.0, 103.0, 99.0, 102.0, 3.0, 2),
        ("NVDA", minute - timedelta(minutes=3), 100.0, 108.0, 95.0, 104.0, 10.0, 4),
        ("NVDA", minute - timedelta(minutes=2), 104.0, 106.0, 103.0, 105.0, 6.0, 3),
        ("AMZN", minute, 200.0, 205.0, 198.0, 201.0, 5.0, 1),
    ])

    rows = api_db.read_candles(e2e_db, "TSLA", 1)
    assert len(rows) == 0

def test_candles_older_than_the_window_are_excluded(e2e_db, api_db):
    minute= base_minute()
    insert_candles(e2e_db, [
        ("NVDA", minute - timedelta(minutes=120), 101.0, 103.0, 99.0, 102.0, 3.0, 2),
        ("NVDA", minute - timedelta(minutes=3), 100.0, 108.0, 95.0, 104.0, 10.0, 4),
    ])

    rows = api_db.read_candles(e2e_db, "NVDA", 1)

    assert len(rows) == 1
    assert rows[0].minute == minute - timedelta(minutes=3)

def test_rows_come_back_oldest_first(e2e_db, api_db):
    minute= base_minute()
    insert_candles(e2e_db, [
        ("NVDA", minute - timedelta(minutes=1), 101.0, 103.0, 99.0, 102.0, 3.0, 2),
        ("NVDA", minute - timedelta(minutes=3), 100.0, 108.0, 95.0, 104.0, 10.0, 4),
        ("NVDA", minute - timedelta(minutes=2), 104.0, 106.0, 103.0, 105.0, 6.0, 3)
    ])

    rows = api_db.read_candles(e2e_db, "NVDA", 1)
    assert [row.minute for row in rows] == [
        minute - timedelta(minutes=3),
        minute - timedelta(minutes=2),
        minute - timedelta(minutes=1),
    ]
