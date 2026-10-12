from datetime import UTC, date, datetime

from live_prices import read_live_prices, write_live_prices


def values(price, trades_today=1003):
    return {
        "price": price,
        "volume": 20.0,
        "trade_ts": datetime(2026, 10, 12, 14, 0, 3, tzinfo=UTC),
        "day": date(2026, 10, 12),
        "day_open": 225.0,
        "day_high": 231.0,
        "day_low": 224.0,
        "trades_today": trades_today,
    }


def test_a_written_price_reads_back_unchanged(redis_client):
    write_live_prices(redis_client, {"AAPL": values(226.0)})

    assert read_live_prices(redis_client, ["AAPL"]) == {"AAPL": values(226.0)}


def test_a_symbol_never_written_reads_as_empty(redis_client):
    assert read_live_prices(redis_client, ["NVDA"]) == {"NVDA": {}}


def test_several_symbols_go_through_one_call_each_way(redis_client):
    write_live_prices(redis_client, {"AAPL": values(226.0), "NVDA": values(130.5)})

    stored = read_live_prices(redis_client, ["AAPL", "NVDA", "TSLA"])

    assert stored == {"AAPL": values(226.0), "NVDA": values(130.5), "TSLA": {}}


def test_a_newer_write_replaces_the_older_one(redis_client):
    write_live_prices(redis_client, {"AAPL": values(226.0, trades_today=1003)})
    write_live_prices(redis_client, {"AAPL": values(227.5, trades_today=1004)})

    assert read_live_prices(redis_client, ["AAPL"]) == {
        "AAPL": values(227.5, trades_today=1004)
    }


def test_the_hash_lives_where_the_dashboard_looks_for_it(redis_client):
    """The dashboard reads price:<SYMBOL> with plain strings in it."""
    write_live_prices(redis_client, {"AAPL": values(226.0)})

    assert redis_client.hget("price:AAPL", "price") == "226.0"
    assert redis_client.hget("price:AAPL", "day") == "2026-10-12"
