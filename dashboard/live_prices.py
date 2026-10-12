import sys
from datetime import date, datetime

import pandas as pd
import redis

STOCK_SYMBOLS = ("AMZN", "NVDA", "GOOGL", "TSLA", "NFLX")

KEY_PREFIX = "price:"

# Same as the stream: a stopped Redis costs a refresh at most this long.
REDIS_TIMEOUT_SECONDS = 0.5

COLUMNS = [
    "symbol",
    "trade_ts",
    "price",
    "volume",
    "day_open",
    "day_high",
    "day_low",
    "trades_today",
]


def connect(url):
    return redis.Redis.from_url(
        url,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        decode_responses=True,
    )


def _row(symbol, raw, today):
    is_today = date.fromisoformat(raw["day"]) == today

    return {
        "symbol": symbol,
        "trade_ts": datetime.fromisoformat(raw["trade_ts"]),
        "price": float(raw["price"]),
        "volume": float(raw["volume"]),
        "day_open": float(raw["day_open"]) if is_today else None,
        "day_high": float(raw["day_high"]) if is_today else None,
        "day_low": float(raw["day_low"]) if is_today else None,
        "trades_today": int(raw["trades_today"]) if is_today else None,
    }


def read_live_board(client, today, symbols=STOCK_SYMBOLS):
    try:
        pipe = client.pipeline()
        for symbol in symbols:
            pipe.hgetall(f"{KEY_PREFIX}{symbol}")
        hashes = pipe.execute()

        if not all(hashes):
            return None

        rows = [
            _row(symbol, raw, today)
            for symbol, raw in zip(symbols, hashes, strict=True)
        ]
    except Exception as error:
        print(
            f"live prices unavailable: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return None

    return (
        pd.DataFrame(rows, columns=COLUMNS)
        .sort_values("symbol")
        .reset_index(drop=True)
    )
