import pandas as pd

CANDLE_COLUMNS = (
    "symbol", "minute", "open", "high", "low", "close", "volume", "trade_count",
)


def build_candles(trades):
    """raw_trades rows -> one OHLCV row per (symbol, minute).

    Pure: no database, no clock, no configuration. The caller decides which
    rows to hand over and what to do with the result.

    Doing this in pandas rather than a SQL GROUP BY is deliberate. The
    trailing window is small (a few minutes x a few symbols), so moving the
    rows costs nothing, and a pure function is far easier to test. At several
    hundred symbols this aggregation belongs in SQL instead.
    """
    if trades.empty:
        return pd.DataFrame(columns=list(CANDLE_COLUMNS))

    frame = pd.DataFrame({
        "symbol": trades["symbol"],
        "price": pd.to_numeric(trades["price"], errors="coerce"),
        "volume": pd.to_numeric(trades["volume"], errors="coerce").fillna(0.0),
        "trade_ts": trades["trade_ts"],
        "minute": trades["trade_ts"].dt.floor("min"),
    })

    # open and close mean "first and last by TIME". Postgres promises no row
    # ordering without an ORDER BY, so this sort is what makes .first() and
    # .last() below actually correct rather than correct by luck.
    frame = frame.sort_values(["symbol", "minute", "trade_ts"])

    candles = frame.groupby(["symbol", "minute"], as_index=False).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("volume", "sum"),
        trade_count=("price", "size"),
    )

    # Deterministic output: the same input always produces byte-identical
    # rows, which is what makes re-running the upsert a genuine no-op.
    return candles.sort_values(["minute", "symbol"], ignore_index=True)[
        list(CANDLE_COLUMNS)
    ]