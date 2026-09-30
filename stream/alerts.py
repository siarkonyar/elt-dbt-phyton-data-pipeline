ABOVE = "above"


def crossed(alert, trade):
    if trade.symbol != alert.symbol:
        return False

    if alert.direction == ABOVE:
        return trade.price >= alert.threshold

    return trade.price <= alert.threshold


def find_triggered(alerts, trades):
    in_time_order = sorted(trades, key=lambda trade: trade.trade_ts)
    fired = []

    for alert in alerts:
        first = next((t for t in in_time_order if crossed(alert, t)), None)

        if first is None:
            continue

        fired.append({
            "alert_id": alert.alert_id,
            "price": first.price,
            "trade_ts": first.trade_ts,
        })

    return fired
