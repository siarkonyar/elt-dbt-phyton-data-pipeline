
def find_triggered(alerts, prices):
    result = []

    for alert in alerts:
        price = prices.get(alert.symbol)
        if price is None:
            continue
        if (price >= alert.threshold and alert.direction == "above") or (price <= alert.threshold and alert.direction == "below"):
            result.append({
                "alert_id": alert.alert_id,
                "symbol": alert.symbol,
                "direction": alert.direction,
                "threshold": float(alert.threshold),
                "price": price,
            })


    return result

def latest_closes(candles):
    minute_map = {}
    price_map = {}

    for candle in candles.itertuples(index=False):
        if minute_map.get(candle.symbol) is None or candle.minute > minute_map.get(candle.symbol):
            minute_map[candle.symbol] = candle.minute
            price_map[candle.symbol] = float(candle.close)

    return price_map