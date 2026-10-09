from datetime import UTC, date, datetime

from db import read_day_stats
from socket_client import Trade
from writer import insert_trades

DAY = date(2026, 10, 8)


def make_trade(symbol, when, price):
    return Trade(symbol=symbol, trade_ts=when, price=price, volume=1.0, conditions="")


def test_the_day_is_summed_up_per_symbol(stream_db):
    insert_trades(stream_db, (
        # Inserted out of time order: the open is the earliest by time.
        make_trade("AAPL", datetime(2026, 10, 8, 15, 0, tzinfo=UTC), 230.0),
        make_trade("AAPL", datetime(2026, 10, 8, 9, 0, tzinfo=UTC), 225.0),
        make_trade("AAPL", datetime(2026, 10, 8, 12, 0, tzinfo=UTC), 224.0),
    ))

    stats = read_day_stats(stream_db, ("AAPL",), DAY)

    assert stats["AAPL"] == {
        "day": DAY,
        "day_open": 225.0,
        "day_high": 230.0,
        "day_low": 224.0,
        "trades_today": 3,
    }


def test_a_symbol_with_no_trades_that_day_gets_nothing(stream_db):
    insert_trades(stream_db, (
        make_trade("AAPL", datetime(2026, 10, 8, 9, 0, tzinfo=UTC), 225.0),
    ))

    stats = read_day_stats(stream_db, ("AAPL", "NVDA"), DAY)

    assert stats["NVDA"] == {}


def test_only_trades_inside_the_utc_day_count(stream_db):
    insert_trades(stream_db, (
        make_trade("AAPL", datetime(2026, 10, 7, 23, 59, 59, tzinfo=UTC), 999.0),
        make_trade("AAPL", datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC), 225.0),
        make_trade("AAPL", datetime(2026, 10, 9, 0, 0, 0, tzinfo=UTC), 1.0),
    ))

    stats = read_day_stats(stream_db, ("AAPL",), DAY)

    assert stats["AAPL"]["trades_today"] == 1
    assert stats["AAPL"]["day_open"] == 225.0
