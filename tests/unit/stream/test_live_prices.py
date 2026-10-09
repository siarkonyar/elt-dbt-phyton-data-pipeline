from datetime import UTC, date, datetime

from live_prices import from_redis, merge, to_redis
from socket_client import Trade

DAY = date(2026, 10, 8)


def at(second):
    return datetime(2026, 10, 8, 14, 0, second, tzinfo=UTC)


def trade(second, price, volume):
    return Trade(
        symbol="AAPL", trade_ts=at(second), price=price, volume=volume, conditions=""
    )


# The worked example from the design. The list order is deliberately not the
# time order: the latest trade (14:00:03) is last, the earliest (14:00:01) is
# in the middle.
BATCH = (
    trade(2, 228.50, 10.0),
    trade(1, 231.00, 5.0),
    trade(3, 226.00, 20.0),
)

OLD = {
    "price": 227.00,
    "volume": 50.0,
    "trade_ts": at(0),
    "day": DAY,
    "day_open": 225.00,
    "day_high": 230.00,
    "day_low": 224.00,
    "trades_today": 1000,
}


def test_price_volume_and_time_come_from_the_latest_trade_by_time():
    new = merge(OLD, BATCH)

    assert new["price"] == 226.00
    assert new["volume"] == 20.0
    assert new["trade_ts"] == at(3)


def test_day_is_the_utc_date_of_the_latest_trade():
    assert merge(OLD, BATCH)["day"] == DAY


def test_an_existing_day_open_is_kept():
    """Trades happened earlier today, so the open is already known."""
    assert merge(OLD, BATCH)["day_open"] == 225.00


def test_day_high_and_low_combine_the_old_values_with_the_batch():
    new = merge(OLD, BATCH)

    assert new["day_high"] == 231.00
    assert new["day_low"] == 224.00


def test_trades_today_adds_the_batch_to_the_old_count():
    assert merge(OLD, BATCH)["trades_today"] == 1003


def test_with_nothing_stored_the_day_starts_from_the_batch():
    """First trades of the day: the open is the earliest trade by time."""
    new = merge({}, BATCH)

    assert new["day"] == DAY
    assert new["day_open"] == 231.00
    assert new["day_high"] == 231.00
    assert new["day_low"] == 226.00
    assert new["trades_today"] == 3
    assert new["price"] == 226.00


def test_the_old_values_are_not_modified():
    before = dict(OLD)

    merge(OLD, BATCH)

    assert OLD == before


# --- to_redis / from_redis ---

def test_every_value_is_stored_as_a_string():
    """Redis has no numbers or dates, only strings."""
    assert all(isinstance(value, str) for value in to_redis(OLD).values())


def test_values_come_back_from_redis_unchanged():
    assert from_redis(to_redis(OLD)) == OLD


def test_a_missing_hash_reads_as_empty():
    """HGETALL on a key that does not exist returns {}."""
    assert from_redis({}) == {}
