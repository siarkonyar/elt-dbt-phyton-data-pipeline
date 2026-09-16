from sqlalchemy import text

INSERT_ALERT_SQL = text(
    """
    INSERT INTO price_alerts (symbol, direction, threshold)
    VALUES (:symbol, :direction, :threshold)
    RETURNING alert_id
    """
)


def make_alert(connection, symbol="NVDA", direction="above", threshold=100.0):
    """Put one waiting alert in the table and hand back its id."""
    return connection.execute(
        INSERT_ALERT_SQL,
        {"symbol": symbol, "direction": direction, "threshold": threshold},
    ).scalar_one()


def read_alert(connection, alert_id):
    return connection.execute(
        text("SELECT * FROM price_alerts WHERE alert_id = :id"), {"id": alert_id}
    ).one()


def test_a_waiting_alert_comes_back(rollup_tables, rollup_db):
    alert_id = make_alert(rollup_tables)

    row = rollup_db.read_pending_alerts(rollup_tables)[0]

    assert row.alert_id == alert_id
    assert row.symbol == "NVDA"
    assert row.direction == "above"
    assert float(row.threshold) == 100.0

def test_an_alert_that_already_fired_does_not_come_back(rollup_tables, rollup_db, rollup_writer):
    alert_id = make_alert(rollup_tables)

    rollup_writer.mark_triggered(
        rollup_tables, [{"alert_id": alert_id, "price": 104.0}]
    )

    rows = rollup_db.read_pending_alerts(rollup_tables)

    assert len(rows) == 0

def test_alerts_come_back_as_rows_read_by_attribute(rollup_tables, rollup_db, rollup_alerts):
    make_alert(rollup_tables, symbol="NVDA", direction="above", threshold=100.0)
    make_alert(rollup_tables, symbol="AMZN", direction="below", threshold=200.0)

    pending = rollup_db.read_pending_alerts(rollup_tables)
    fired = rollup_alerts.find_triggered(pending, {"NVDA": 104.0, "AMZN": 198.0})

    assert sorted(row["symbol"] for row in fired) == ["AMZN", "NVDA"]


def test_mark_triggered_stamps_the_time_and_the_price(rollup_tables, rollup_writer):
    alert_id = make_alert(rollup_tables)                      # arrange

    rollup_writer.mark_triggered(                             # act
        rollup_tables, [{"alert_id": alert_id, "price": 104.0}]
    )

    row = read_alert(rollup_tables, alert_id)                 # assert
    assert row.triggered_at is not None
    assert float(row.triggered_price) == 104.0
