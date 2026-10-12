from datetime import date, datetime

import redis

KEY_PREFIX = "price:"

# Half the one-second flush interval: a slow Redis gives up in time and
# leaves the rest of the flush for Postgres.
REDIS_TIMEOUT_SECONDS = 0.5

# Redis stores only strings. Each stored field and how to read it back.
PARSERS = {
    "price": float,
    "volume": float,
    "trade_ts": datetime.fromisoformat,
    "day": date.fromisoformat,
    "day_open": float,
    "day_high": float,
    "day_low": float,
    "trades_today": int,
}


def merge(old, trades):
    """One symbol's stored values plus a batch of its trades -> the new values.

    old is empty when nothing is known about today yet. trades is never empty
    and may arrive in any order. Returns a new dict; old is left untouched.
    """

    latest = max(trades, key=lambda t: t.trade_ts)
    earliest = min(trades, key=lambda t: t.trade_ts)
    high = max(t.price for t in trades)
    low = min(t.price for t in trades)


    trades_today = len(trades)

    result = {
        "day": latest.trade_ts.date(),
        "trade_ts": latest.trade_ts,
        "volume": latest.volume,
        "price": latest.price,
    }

    if old:
        result["day_open"] = old["day_open"]
        if old["day_high"] > high:
            result["day_high"] = old["day_high"]
        else:
            result["day_high"] = high
        if old["day_low"] < low:
            result["day_low"] = old["day_low"]
        else:
            result["day_low"] = low

        trades_today = old["trades_today"] + trades_today
    else:
        result["day_open"] = earliest.price
        result["day_high"] = high
        result["day_low"] = low

    result["trades_today"] = trades_today

    return result


def to_redis(values):
    return {
        field: value.isoformat() if isinstance(value, date) else str(value)
        for field, value in values.items()
    }


def from_redis(raw):
    return {field: PARSERS[field](text) for field, text in raw.items()}


def connect(url):
    """No network traffic yet: redis-py connects on the first command."""
    return redis.Redis.from_url(
        url,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        decode_responses=True,
    )


def _key(symbol):
    return f"{KEY_PREFIX}{symbol}"


def read_live_prices(client, symbols):
    """symbol -> stored values, {} where nothing is stored. One round trip."""
    pipe = client.pipeline()
    for symbol in symbols:
        pipe.hgetall(_key(symbol))

    return {
        symbol: from_redis(raw)
        for symbol, raw in zip(symbols, pipe.execute(), strict=True)
    }


def write_live_prices(client, values_by_symbol):
    """One round trip for every symbol in the batch."""
    pipe = client.pipeline()
    for symbol, values in values_by_symbol.items():
        pipe.hset(_key(symbol), mapping=to_redis(values))
    pipe.execute()
