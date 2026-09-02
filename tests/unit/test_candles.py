from decimal import Decimal

import pandas as pd
from candles import CANDLE_COLUMNS, build_candles

TRADE_COLUMNS = ["symbol", "trade_ts", "price", "volume"]


def at(clock):
    """'12:00:37' -> a UTC timestamp on 2024-01-01."""
    return pd.Timestamp(f"2024-01-01 {clock}", tz="UTC")


def trades_frame(rows):
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def one_symbol(prices_by_time, symbol="NVDA", volume=1.0):
    """{'12:00:10': 100.0} -> a trades frame for a single symbol."""
    return trades_frame(
        [(symbol, at(clock), price, volume) for clock, price in prices_by_time.items()]
    )


# --- shape of the result ---

def test_no_trades_produces_no_candles():
    candles = build_candles(trades_frame([]))

    assert candles.empty


def test_an_empty_result_still_has_the_candle_columns():
    # The writer reads these columns by name. An empty frame without them
    # would turn "nothing to write" into a KeyError.
    candles = build_candles(trades_frame([]))

    assert list(candles.columns) == list(CANDLE_COLUMNS)


def test_the_columns_come_back_in_the_agreed_order():
    candles = build_candles(one_symbol({"12:00:10": 100.0}))

    assert list(candles.columns) == list(CANDLE_COLUMNS)


def test_one_trade_becomes_one_candle():
    candles = build_candles(one_symbol({"12:00:10": 100.0}))

    assert len(candles) == 1


def test_a_single_trade_is_its_own_open_high_low_and_close():
    candles = build_candles(one_symbol({"12:00:10": 100.0}))

    row = candles.iloc[0]
    assert row.open == 100.0
    assert row.high == 100.0
    assert row.low == 100.0
    assert row.close == 100.0


# --- open and close follow the clock, not the row order ---

def test_open_is_the_earliest_price_in_the_minute():
    candles = build_candles(
        one_symbol({"12:00:10": 100.0, "12:00:30": 105.0, "12:00:50": 103.0})
    )

    assert candles.iloc[0].open == 100.0


def test_close_is_the_latest_price_in_the_minute():
    candles = build_candles(
        one_symbol({"12:00:10": 100.0, "12:00:30": 105.0, "12:00:50": 103.0})
    )

    assert candles.iloc[0].close == 103.0


def test_open_and_close_ignore_the_order_the_rows_arrived_in():
    # Postgres promises no ordering without an ORDER BY, so the rows may
    # arrive shuffled. Delete the sort in build_candles and this test fails
    # while every other assertion here still passes.
    shuffled = one_symbol({"12:00:50": 103.0, "12:00:10": 100.0, "12:00:30": 105.0})

    candles = build_candles(shuffled)

    assert candles.iloc[0].open == 100.0
    assert candles.iloc[0].close == 103.0


# --- the rest of the OHLCV row ---

def test_high_is_the_largest_price_in_the_minute():
    candles = build_candles(
        one_symbol({"12:00:10": 100.0, "12:00:30": 108.0, "12:00:50": 103.0})
    )

    assert candles.iloc[0].high == 108.0


def test_low_is_the_smallest_price_in_the_minute():
    candles = build_candles(
        one_symbol({"12:00:10": 100.0, "12:00:30": 108.0, "12:00:50": 95.0})
    )

    assert candles.iloc[0].low == 95.0


def test_volume_is_the_sum_of_the_trades():
    trades = trades_frame([
        ("NVDA", at("12:00:10"), 100.0, 2.0),
        ("NVDA", at("12:00:20"), 101.0, 3.5),
    ])

    candles = build_candles(trades)

    assert candles.iloc[0].volume == 5.5


def test_trade_count_is_the_number_of_trades():
    candles = build_candles(
        one_symbol({"12:00:10": 100.0, "12:00:30": 108.0, "12:00:50": 95.0})
    )

    assert candles.iloc[0].trade_count == 3


# --- grouping ---

def test_seconds_are_floored_away_to_the_minute():
    candles = build_candles(one_symbol({"12:00:37": 100.0}))

    assert candles.iloc[0].minute == at("12:00:00")


def test_trades_in_the_same_minute_collapse_into_one_candle():
    candles = build_candles(one_symbol({"12:00:01": 100.0, "12:00:59": 105.0}))

    assert len(candles) == 1


def test_trades_in_different_minutes_stay_apart():
    candles = build_candles(one_symbol({"12:00:59": 100.0, "12:01:00": 105.0}))

    assert len(candles) == 2
    assert list(candles.minute) == [at("12:00:00"), at("12:01:00")]


def test_two_symbols_in_one_minute_do_not_mix():
    trades = trades_frame([
        ("NVDA", at("12:00:10"), 100.0, 1.0),
        ("AMZN", at("12:00:20"), 200.0, 1.0),
    ])

    candles = build_candles(trades)

    assert len(candles) == 2
    assert dict(zip(candles.symbol, candles.close)) == {"NVDA": 100.0, "AMZN": 200.0}


# --- determinism, which is what makes re-running the upsert a no-op ---

def test_rows_come_back_ordered_by_minute_then_symbol():
    trades = trades_frame([
        ("NVDA", at("12:01:00"), 100.0, 1.0),
        ("AMZN", at("12:00:00"), 200.0, 1.0),
        ("NVDA", at("12:00:00"), 101.0, 1.0),
    ])

    candles = build_candles(trades)

    assert list(zip(candles.symbol, candles.minute)) == [
        ("AMZN", at("12:00:00")),
        ("NVDA", at("12:00:00")),
        ("NVDA", at("12:01:00")),
    ]


def test_the_index_is_reset_so_shuffled_input_gives_identical_output():
    ordered = trades_frame([
        ("AMZN", at("12:00:20"), 200.0, 1.0),
        ("NVDA", at("12:00:10"), 100.0, 1.0),
    ])
    shuffled = ordered.iloc[::-1]

    assert build_candles(ordered).equals(build_candles(shuffled))


# --- values arriving from the database ---

def test_decimal_prices_from_postgres_become_numbers():
    # A NUMERIC column comes back as Decimal, which cannot be compared with
    # floats or summed the way the aggregation needs.
    trades = trades_frame([
        ("NVDA", at("12:00:10"), Decimal("100.5"), Decimal("2")),
        ("NVDA", at("12:00:20"), Decimal("101.5"), Decimal("3")),
    ])

    candles = build_candles(trades)

    assert candles.iloc[0].open == 100.5
    assert candles.iloc[0].close == 101.5
    assert candles.iloc[0].volume == 5.0


def test_a_missing_volume_counts_as_zero():
    # Not every feed sends a size. Without the fillna the sum becomes NaN and
    # poisons the whole minute.
    trades = trades_frame([
        ("NVDA", at("12:00:10"), 100.0, None),
        ("NVDA", at("12:00:20"), 101.0, 3.0),
    ])

    candles = build_candles(trades)

    assert candles.iloc[0].volume == 3.0


def test_a_trade_with_no_volume_is_still_counted():
    trades = trades_frame([
        ("NVDA", at("12:00:10"), 100.0, None),
        ("NVDA", at("12:00:20"), 101.0, 3.0),
    ])

    candles = build_candles(trades)

    assert candles.iloc[0].trade_count == 2


# --- purity ---

def test_the_trades_handed_in_are_left_alone():
    trades = one_symbol({"12:00:50": 103.0, "12:00:10": 100.0})
    before = trades.copy(deep=True)

    build_candles(trades)

    assert trades.equals(before)
