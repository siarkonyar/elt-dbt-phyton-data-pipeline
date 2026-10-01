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

def _float_or_none(value):
    return None if value is None else float(value)

def _iso_or_none(value):
    return None if value is None else value.isoformat()

def alert_to_dict(row):
    """triggered_at and triggered_price stay None until the stream fires it."""
    return {
        "alert_id": row.alert_id,
        "username": row.username,
        "symbol": row.symbol,
        "direction": row.direction,
        "threshold": float(row.threshold),
        "created_at": row.created_at.isoformat(),
        "triggered_at": _iso_or_none(row.triggered_at),
        "triggered_price": _float_or_none(row.triggered_price),
    }
