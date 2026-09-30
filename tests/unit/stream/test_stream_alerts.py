from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from alerts import find_triggered
from socket_client import Trade

BASE_TIME = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def trade(price, symbol="NVDA", seconds=0):
    return Trade(
        symbol=symbol,
        trade_ts=BASE_TIME + timedelta(seconds=seconds),
        price=price,
        volume=1.0,
        conditions="",
    )


def alert(alert_id=1, symbol="NVDA", direction="above", threshold=100.0):
    """The shape a row from the pending-alerts query has."""
    return SimpleNamespace(
        alert_id=alert_id, symbol=symbol, direction=direction, threshold=threshold
    )


def fired_ids(alerts, trades):
    return [fired["alert_id"] for fired in find_triggered(alerts, trades)]


def test_a_spike_inside_one_batch_fires_the_alert():
    """The reason the check moved out of the rollup. The last price is back
    under 100, but one trade in between went over it."""
    trades = [
        trade(99.00, seconds=0),
        trade(102.00, seconds=1),
        trade(99.50, seconds=2),
    ]

    assert find_triggered([alert(threshold=100.0)], trades) == [
        {"alert_id": 1, "price": 102.00, "trade_ts": BASE_TIME + timedelta(seconds=1)}
    ]


def test_an_above_alert_stays_quiet_when_no_trade_reaches_it():
    assert fired_ids([alert(threshold=110.0)], [trade(104.0)]) == []


def test_an_above_alert_fires_at_exactly_its_threshold():
    assert fired_ids([alert(threshold=104.0)], [trade(104.0)]) == [1]


def test_a_below_alert_fires_when_a_trade_drops_to_it():
    trades = [trade(101.0, seconds=0), trade(97.0, seconds=1), trade(100.5, seconds=2)]

    assert fired_ids([alert(direction="below", threshold=98.0)], trades) == [1]


def test_a_below_alert_stays_quiet_when_no_trade_drops_to_it():
    assert fired_ids([alert(direction="below", threshold=90.0)], [trade(104.0)]) == []


def test_a_below_alert_fires_at_exactly_its_threshold():
    assert fired_ids([alert(direction="below", threshold=104.0)], [trade(104.0)]) == [1]


def test_a_trade_for_another_symbol_does_not_fire_the_alert():
    """AMZN at 200 is above 100, but the alert is watching NVDA."""
    assert fired_ids([alert(symbol="NVDA")], [trade(200.0, symbol="AMZN")]) == []


def test_the_earliest_crossing_trade_is_the_one_recorded():
    """Finnhub does not promise time order inside one message. The alert must
    record the moment it first crossed, not whichever trade was listed first."""
    later = trade(105.0, seconds=5)
    earlier = trade(101.0, seconds=1)

    fired = find_triggered([alert(threshold=100.0)], [later, earlier])[0]

    assert fired["price"] == 101.0
    assert fired["trade_ts"] == earlier.trade_ts


def test_a_decimal_threshold_from_postgres_is_compared_correctly():
    """NUMERIC comes back as Decimal while trade prices are floats."""
    assert fired_ids([alert(threshold=Decimal("100.00"))], [trade(100.5)]) == [1]


def test_only_the_alerts_that_crossed_come_back():
    alerts = [
        alert(alert_id=1, threshold=100.0),
        alert(alert_id=2, threshold=500.0),
        alert(alert_id=3, symbol="AMZN", direction="below", threshold=210.0),
    ]
    trades = [trade(104.0), trade(200.0, symbol="AMZN")]

    assert fired_ids(alerts, trades) == [1, 3]


def test_an_empty_batch_fires_nothing():
    assert find_triggered([alert()], []) == []


def test_no_waiting_alerts_fire_nothing():
    assert find_triggered([], [trade(104.0)]) == []
