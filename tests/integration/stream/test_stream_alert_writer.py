"""The stream's two alert queries against a real Postgres.

price_alerts belongs to the api's schema, so these use api_tables. The stream
reads and stamps a table it does not own - deliberate, because only the api
may create alerts, and only the stream sees every trade.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from db import read_pending_alerts
from main import check_alerts
from socket_client import Trade
from writer import mark_triggered

TRADE_TIME = datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC)

INSERT_USER_SQL = text(
    """
    INSERT INTO users (username, password_hash)
    VALUES ('ada', '$2b$04$synthetic-value-for-tests-only')
    RETURNING user_id
    """
)

INSERT_ALERT_SQL = text(
    """
    INSERT INTO price_alerts (user_id, symbol, direction, threshold)
    VALUES (:user_id, :symbol, :direction, :threshold)
    RETURNING alert_id
    """
)

READ_ALERT_SQL = text("SELECT * FROM price_alerts WHERE alert_id = :alert_id")


def make_alert(connection, symbol="NVDA", direction="above", threshold=100.0):
    user_id = connection.execute(INSERT_USER_SQL).scalar_one()
    return connection.execute(
        INSERT_ALERT_SQL,
        {
            "user_id": user_id,
            "symbol": symbol,
            "direction": direction,
            "threshold": threshold,
        },
    ).scalar_one()


def read_alert(connection, alert_id):
    return connection.execute(READ_ALERT_SQL, {"alert_id": alert_id}).one()


def fired(alert_id, price=102.0, trade_ts=TRADE_TIME):
    """The shape alerts.find_triggered hands back."""
    return {"alert_id": alert_id, "price": price, "trade_ts": trade_ts}


def test_a_waiting_alert_comes_back_with_what_the_check_needs(api_tables):
    alert_id = make_alert(api_tables)

    row = read_pending_alerts(api_tables)[0]

    assert row.alert_id == alert_id
    assert row.symbol == "NVDA"
    assert row.direction == "above"
    assert float(row.threshold) == 100.0


def test_a_fired_alert_is_stamped_with_the_trades_own_price_and_time(api_tables):
    """Not now(): the flush runs up to a second after the trade happened, and
    the alert should say when the price actually crossed."""
    alert_id = make_alert(api_tables)

    mark_triggered(api_tables, [fired(alert_id)])

    row = read_alert(api_tables, alert_id)
    assert float(row.triggered_price) == 102.0
    assert row.triggered_at == TRADE_TIME


def test_a_fired_alert_leaves_the_waiting_list(api_tables):
    alert_id = make_alert(api_tables)

    mark_triggered(api_tables, [fired(alert_id)])

    assert read_pending_alerts(api_tables) == []


def test_an_alert_that_already_fired_keeps_its_first_price_and_time(api_tables):
    """The triggered_at IS NULL guard. An alert fires once and then stays put."""
    alert_id = make_alert(api_tables)
    mark_triggered(api_tables, [fired(alert_id)])

    later = TRADE_TIME + timedelta(seconds=30)
    mark_triggered(api_tables, [fired(alert_id, price=999.0, trade_ts=later)])

    row = read_alert(api_tables, alert_id)
    assert float(row.triggered_price) == 102.0
    assert row.triggered_at == TRADE_TIME


def test_nothing_to_mark_touches_nothing(api_tables):
    alert_id = make_alert(api_tables)

    assert mark_triggered(api_tables, []) == 0
    assert read_alert(api_tables, alert_id).triggered_at is None


def test_check_alerts_fires_an_alert_from_a_live_trade(e2e_db):
    """The whole path the flush loop runs: read, decide, stamp. e2e_db is an
    engine, because check_alerts opens its own transaction."""
    with e2e_db.begin() as connection:
        alert_id = make_alert(connection, threshold=100.0)

    spike = Trade(
        symbol="NVDA", trade_ts=TRADE_TIME, price=102.0, volume=1.0, conditions=""
    )

    assert check_alerts(e2e_db, (spike,)) == 1

    with e2e_db.connect() as connection:
        row = read_alert(connection, alert_id)

    assert float(row.triggered_price) == 102.0
    assert row.triggered_at == TRADE_TIME
