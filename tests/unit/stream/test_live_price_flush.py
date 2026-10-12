from contextlib import contextmanager
from datetime import UTC, date, datetime

import redis

import main
from live_prices import merge
from main import load_live_prices, save_live_prices
from socket_client import Trade

TODAY = date(2026, 10, 9)
YESTERDAY = date(2026, 10, 8)


def trade(symbol, hour, price):
    return Trade(
        symbol=symbol,
        trade_ts=datetime(2026, 10, 9, hour, 0, tzinfo=UTC),
        price=price,
        volume=1.0,
        conditions="",
    )


def stats(day):
    return {
        "day": day,
        "day_open": 100.0,
        "day_high": 110.0,
        "day_low": 90.0,
        "trades_today": 10,
    }


def must_not_be_called(*args, **kwargs):
    raise AssertionError("called when it should not have been")


def redis_is_down(*args, **kwargs):
    raise redis.ConnectionError("Connection refused")


class FakeEngine:
    @contextmanager
    def begin(self):
        yield "connection"


class EngineThatMustNotBeUsed:
    def begin(self):
        raise AssertionError("opened a transaction")


class SeedRecorder:
    """Stands in for read_day_stats and remembers what it was asked for."""

    def __init__(self):
        self.calls = []

    def __call__(self, connection, symbols, day):
        self.calls.append((list(symbols), day))
        return {symbol: stats(day) for symbol in symbols}


# --- load_live_prices ---

def test_an_empty_batch_touches_neither_redis_nor_postgres(monkeypatch):
    """The market is closed most of the day; those flushes cost nothing."""
    monkeypatch.setattr(main, "read_live_prices", must_not_be_called)

    assert load_live_prices("client", EngineThatMustNotBeUsed(), (), False) == {}


def test_a_reseed_skips_redis_and_seeds_every_symbol(monkeypatch):
    seed = SeedRecorder()
    monkeypatch.setattr(main, "read_live_prices", must_not_be_called)
    monkeypatch.setattr(main, "read_day_stats", seed)
    batch = (trade("NVDA", 14, 130.0), trade("AAPL", 14, 230.0))

    stored = load_live_prices("client", FakeEngine(), batch, True)

    assert seed.calls == [(["AAPL", "NVDA"], TODAY)]
    assert stored == {"AAPL": stats(TODAY), "NVDA": stats(TODAY)}


def test_only_missing_or_old_hashes_are_seeded(monkeypatch):
    seed = SeedRecorder()
    todays = {**stats(TODAY), "price": 230.0}
    monkeypatch.setattr(
        main,
        "read_live_prices",
        lambda client, symbols: {
            "AAPL": todays,
            "NVDA": stats(YESTERDAY),
            "TSLA": {},
        },
    )
    monkeypatch.setattr(main, "read_day_stats", seed)
    batch = (
        trade("AAPL", 14, 231.0),
        trade("NVDA", 14, 131.0),
        trade("TSLA", 14, 251.0),
    )

    stored = load_live_prices("client", FakeEngine(), batch, False)

    assert seed.calls == [(["NVDA", "TSLA"], TODAY)]
    assert stored["AAPL"] is todays
    assert stored["NVDA"] == stats(TODAY)
    assert stored["TSLA"] == stats(TODAY)


def test_no_seed_query_when_every_hash_is_from_today(monkeypatch):
    monkeypatch.setattr(
        main, "read_live_prices", lambda client, symbols: {"AAPL": stats(TODAY)}
    )
    monkeypatch.setattr(main, "read_day_stats", must_not_be_called)

    stored = load_live_prices(
        "client", EngineThatMustNotBeUsed(), (trade("AAPL", 14, 231.0),), False
    )

    assert stored == {"AAPL": stats(TODAY)}


def test_a_redis_failure_while_loading_is_logged_and_skips_redis(
    monkeypatch, capsys
):
    monkeypatch.setattr(main, "read_live_prices", redis_is_down)

    stored = load_live_prices(
        "client", FakeEngine(), (trade("AAPL", 14, 231.0),), False
    )

    assert stored is None
    assert "ConnectionError" in capsys.readouterr().err


# --- save_live_prices ---

def test_each_symbol_is_saved_as_its_merged_values(monkeypatch):
    written = {}
    monkeypatch.setattr(
        main, "write_live_prices", lambda client, values: written.update(values)
    )
    aapl = (trade("AAPL", 14, 230.0), trade("AAPL", 15, 231.0))
    nvda = (trade("NVDA", 14, 130.0),)
    stored = {"AAPL": stats(TODAY), "NVDA": {}}

    assert save_live_prices("client", stored, aapl + nvda) is True
    assert written == {
        "AAPL": merge(stats(TODAY), list(aapl)),
        "NVDA": merge({}, list(nvda)),
    }


def test_a_redis_failure_while_saving_is_logged_and_reported(monkeypatch, capsys):
    monkeypatch.setattr(main, "write_live_prices", redis_is_down)

    saved = save_live_prices(
        "client", {"AAPL": stats(TODAY)}, (trade("AAPL", 14, 231.0),)
    )

    assert saved is False
    assert "ConnectionError" in capsys.readouterr().err
