from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from alerts import find_triggered, latest_closes
from candles import CANDLE_COLUMNS


def at(clock):
    return pd.Timestamp(f"2024-01-01 {clock}", tz="UTC")


def candles_frame(rows):
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "minute": minute,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "trade_count": 1,
            }
            for symbol, minute, close in rows
        ],
        columns=list(CANDLE_COLUMNS),
    )


def alert(alert_id, symbol, direction, threshold):
    return SimpleNamespace(
        alert_id=alert_id,
        symbol=symbol,
        direction=direction,
        threshold=threshold,
    )


def fired_ids(alerts, prices):
    return [fired["alert_id"] for fired in find_triggered(alerts, prices)]


# --- candle frames ---

EMPTY = candles_frame([])

# three minutes of one symbol -> {"NVDA": 104.0}, the NEWEST close
ONE_SYMBOL = candles_frame([
    ("NVDA", at("12:00"), 100.0),
    ("NVDA", at("12:01"), 105.0),
    ("NVDA", at("12:02"), 104.0),
])

# the same rows out of order -> still 104.0
SHUFFLED = candles_frame([
    ("NVDA", at("12:01"), 105.0),
    ("NVDA", at("12:02"), 104.0),
    ("NVDA", at("12:00"), 100.0),
])

# two symbols must not bleed into each other
TWO_SYMBOLS = candles_frame([
    ("NVDA", at("12:00"), 100.0),
    ("NVDA", at("12:01"), 104.0),
    ("AMZN", at("12:00"), 200.0),
    ("AMZN", at("12:01"), 198.0),
])

# a NUMERIC column comes back from Postgres as Decimal
DECIMAL_CLOSE = candles_frame([("NVDA", at("12:00"), Decimal("104.25"))])


# --- alerts, all judged against these prices ---

PRICES = {"NVDA": 104.0, "AMZN": 198.0}

ABOVE_HIT   = alert(1, "NVDA", "above", 100.0)   # 104 >= 100 -> fires
ABOVE_MISS  = alert(2, "NVDA", "above", 110.0)   # 104 < 110  -> does not fire
ABOVE_EXACT = alert(3, "NVDA", "above", 104.0)   # exactly equal -> fires

BELOW_HIT   = alert(4, "NVDA", "below", 110.0)   # 104 <= 110 -> fires
BELOW_MISS  = alert(5, "NVDA", "below", 100.0)   # 104 > 100  -> does not fire
BELOW_EXACT = alert(6, "NVDA", "below", 104.0)   # exactly equal -> fires

# a second symbol, to prove nothing is hardcoded to one
OTHER_SYMBOL = alert(7, "AMZN", "below", 200.0)  # 198 <= 200 -> fires

# no candle for TSLA this run, so this one must be skipped entirely
NO_PRICE = alert(8, "TSLA", "below", 10_000.0)

# a NUMERIC column comes back from Postgres as Decimal
DECIMAL_THRESHOLD = alert(9, "NVDA", "above", Decimal("100.00"))

# hits, misses, a skip and a second symbol, deliberately out of id order
MIXED = [ABOVE_EXACT, ABOVE_HIT, ABOVE_MISS, NO_PRICE, OTHER_SYMBOL]


# --- latest_closes ---

def test_no_candles_produce_no_prices():
    assert latest_closes(EMPTY) == {}


def test_a_symbol_maps_to_its_newest_close():
    assert latest_closes(ONE_SYMBOL) == {"NVDA": 104.0}


def test_the_newest_close_is_found_by_minute_not_by_row_order():
    assert latest_closes(SHUFFLED) == {"NVDA": 104.0}


def test_each_symbol_keeps_its_own_close():
    assert latest_closes(TWO_SYMBOLS) == {"NVDA": 104.0, "AMZN": 198.0}


def test_decimal_closes_from_postgres_become_floats():
    price = latest_closes(DECIMAL_CLOSE)["NVDA"]

    assert price == 104.25
    assert isinstance(price, float)


def test_the_candles_handed_in_are_left_alone():
    candles = candles_frame([("NVDA", at("12:00"), 100.0)])
    before = candles.copy(deep=True)

    latest_closes(candles)

    assert candles.equals(before)


def test_no_alerts_fire_nothing():
    assert find_triggered([], PRICES) == []


def test_alerts_fire_nothing_when_no_candles_were_built():
    assert find_triggered([ABOVE_HIT, BELOW_HIT], {}) == []


def test_an_above_alert_fires_once_the_price_reaches_it():
    assert fired_ids([ABOVE_HIT], PRICES) == [1]


def test_an_above_alert_stays_quiet_below_its_threshold():
    assert fired_ids([ABOVE_MISS], PRICES) == []


def test_an_above_alert_fires_at_exactly_its_threshold():
    assert fired_ids([ABOVE_EXACT], PRICES) == [3]


def test_a_below_alert_fires_once_the_price_reaches_it():
    assert fired_ids([BELOW_HIT], PRICES) == [4]


def test_a_below_alert_stays_quiet_above_its_threshold():
    assert fired_ids([BELOW_MISS], PRICES) == []


def test_a_below_alert_fires_at_exactly_its_threshold():
    assert fired_ids([BELOW_EXACT], PRICES) == [6]


def test_an_alert_whose_symbol_had_no_candle_is_skipped():
    assert fired_ids([NO_PRICE], PRICES) == []


def test_alerts_on_a_second_symbol_fire_too():
    assert fired_ids([OTHER_SYMBOL], PRICES) == [7]


def test_only_the_alerts_that_met_their_condition_come_back():
    assert fired_ids(MIXED, PRICES) == [3, 1, 7]


def test_fired_alerts_keep_the_order_they_arrived_in():
    fired = fired_ids(MIXED, PRICES)

    assert fired != sorted(fired)

def test_a_fired_alert_carries_the_whole_story():
    assert find_triggered([ABOVE_HIT], PRICES) == [
        {
            "alert_id": 1,
            "symbol": "NVDA",
            "direction": "above",
            "threshold": 100.0,
            "price": 104.0,
        }
    ]


def test_a_decimal_threshold_comes_back_as_a_float():
    threshold = find_triggered([DECIMAL_THRESHOLD], PRICES)[0]["threshold"]

    assert threshold == 100.0
    assert isinstance(threshold, float)


def test_the_alerts_handed_in_are_left_alone():
    one = alert(1, "NVDA", "above", 100.0)
    before = vars(one).copy()

    find_triggered([one], PRICES)

    assert vars(one) == before
