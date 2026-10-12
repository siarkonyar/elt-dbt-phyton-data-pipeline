from datetime import date

import pandas as pd
import redis

from config import DEFAULTS, parse_symbols  # stream/config.py, see conftest

TODAY = date(2026, 10, 12)


def stored(price, day="2026-10-12"):
    """A hash exactly as the stream's to_redis writes it: all strings."""
    return {
        "price": str(price),
        "volume": "20.0",
        "trade_ts": "2026-10-12T14:00:03+00:00",
        "day": day,
        "day_open": "225.0",
        "day_high": "231.0",
        "day_low": "224.0",
        "trades_today": "1003",
    }


class FakePipeline:
    def __init__(self, hashes):
        self.hashes = hashes
        self.keys = []

    def hgetall(self, key):
        self.keys.append(key)

    def execute(self):
        # HGETALL on a key that does not exist returns {}.
        return [self.hashes.get(key, {}) for key in self.keys]


class FakeRedis:
    def __init__(self, hashes):
        self.hashes = hashes

    def pipeline(self):
        return FakePipeline(self.hashes)


class DownPipeline(FakePipeline):
    def execute(self):
        raise redis.ConnectionError("Connection refused")


class RedisThatIsDown:
    def pipeline(self):
        return DownPipeline({})


def test_todays_hashes_become_the_board_sorted_by_symbol(dashboard_live_prices):
    client = FakeRedis({"price:NVDA": stored(130.5), "price:AMZN": stored(180.25)})

    board = dashboard_live_prices.read_live_board(client, TODAY, ("NVDA", "AMZN"))

    assert list(board.columns) == dashboard_live_prices.COLUMNS
    assert list(board["symbol"]) == ["AMZN", "NVDA"]
    assert list(board["price"]) == [180.25, 130.5]
    assert list(board["trades_today"]) == [1003, 1003]
    assert board.iloc[0]["day_open"] == 225.0


def test_a_hash_from_another_day_keeps_its_price_but_blanks_the_day(
    dashboard_live_prices,
):
    """What LATEST_SQL shows before the first trade of a new day."""
    client = FakeRedis({"price:AMZN": stored(180.25, day="2026-10-09")})

    row = dashboard_live_prices.read_live_board(client, TODAY, ("AMZN",)).iloc[0]

    assert row["price"] == 180.25
    for field in ("day_open", "day_high", "day_low", "trades_today"):
        assert pd.isna(row[field])


def test_one_missing_symbol_sends_the_whole_board_to_postgres(
    dashboard_live_prices,
):
    client = FakeRedis({"price:AMZN": stored(180.25)})

    board = dashboard_live_prices.read_live_board(client, TODAY, ("AMZN", "NVDA"))

    assert board is None


def test_a_redis_error_is_logged_and_sends_the_board_to_postgres(
    dashboard_live_prices, capsys
):
    board = dashboard_live_prices.read_live_board(RedisThatIsDown(), TODAY, ("AMZN",))

    assert board is None
    assert "ConnectionError" in capsys.readouterr().err


def test_the_symbols_match_the_stream_default(dashboard_live_prices):
    """The two lists are kept in sync by hand; this catches them drifting."""
    expected = parse_symbols(DEFAULTS["STOCK_SYMBOLS"])

    assert dashboard_live_prices.STOCK_SYMBOLS == expected
