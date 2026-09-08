CANDLE_COLUMNS = (
    "symbol", "minute", "open", "high", "low", "close", "volume", "trade_count",
)

def candle_to_dict(row):
    return {
        "symbol": row.symbol,
        "minute": row.minute.isoformat(),
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
        "volume": float(row.volume),
        "trade_count": int(row.trade_count),
    }