
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