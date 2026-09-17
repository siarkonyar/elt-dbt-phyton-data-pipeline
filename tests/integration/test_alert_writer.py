from sqlalchemy import text

INSERT_ALERT_SQL = text(
    """
    INSERT INTO price_alerts (symbol, direction, threshold)
    VALUES (:symbol, :direction, :threshold)
    RETURNING alert_id
    """
)

FIRE_ALERT_SQL = text(
    """
    UPDATE price_alerts
      SET triggered_at = now(), triggered_price = :price
    WHERE alert_id = :alert_id
    """
)

READ_ALERT_SQL = text("SELECT * FROM price_alerts WHERE alert_id = :alert_id")


def make_alert(connection, symbol="NVDA", direction="above", threshold=100.0):
    """Put one waiting alert in the table and hand back its id."""
    return connection.execute(
        INSERT_ALERT_SQL,
        {"symbol": symbol, "direction": direction, "threshold": threshold},
    ).scalar_one()


def fire_alert(connection, alert_id, price=104.0):
    connection.execute(FIRE_ALERT_SQL, {"alert_id": alert_id, "price": price})


def read_alert(connection, alert_id):
    return connection.execute(READ_ALERT_SQL, {"alert_id": alert_id}).one()


def test_a_waiting_alert_comes_back(rollup_tables, rollup_db):
    alert_id = make_alert(rollup_tables)

    row = rollup_db.read_pending_alerts(rollup_tables)[0]

    assert row.alert_id == alert_id
    assert row.symbol == "NVDA"
    assert row.direction == "above"
    assert float(row.threshold) == 100.0


def test_an_alert_that_already_fired_does_not_come_back(rollup_tables, rollup_db):
    alert_id = make_alert(rollup_tables)
    fire_alert(rollup_tables, alert_id)

    assert rollup_db.read_pending_alerts(rollup_tables) == []


def test_every_waiting_alert_comes_back(rollup_tables, rollup_db):
    make_alert(rollup_tables, symbol="NVDA")
    make_alert(rollup_tables, symbol="AMZN", direction="below", threshold=200.0)

    rows = rollup_db.read_pending_alerts(rollup_tables)

    assert len(rows) == 2


def test_pending_alerts_are_the_shape_find_triggered_expects(
    rollup_tables, rollup_db, rollup_alerts
):
    make_alert(rollup_tables, symbol="NVDA")
    make_alert(rollup_tables, symbol="AMZN", direction="below", threshold=200.0)

    pending = rollup_db.read_pending_alerts(rollup_tables)
    fired = rollup_alerts.find_triggered(pending, {"NVDA": 104.0, "AMZN": 198.0})

    assert sorted(row["symbol"] for row in fired) == ["AMZN", "NVDA"]


def test_mark_triggered_stamps_the_time_and_the_price(rollup_tables, rollup_writer):
    alert_id = make_alert(rollup_tables)

    marked = rollup_writer.mark_triggered(
        rollup_tables, [{"alert_id": alert_id, "price": 104.0}]
    )

    assert marked == 1
    row = read_alert(rollup_tables, alert_id)
    assert row.triggered_at is not None
    assert float(row.triggered_price) == 104.0


def test_a_fired_alert_leaves_the_waiting_list(
    rollup_tables, rollup_db, rollup_writer
):
    alert_id = make_alert(rollup_tables)

    rollup_writer.mark_triggered(
        rollup_tables, [{"alert_id": alert_id, "price": 104.0}]
    )

    assert rollup_db.read_pending_alerts(rollup_tables) == []


def test_an_alert_that_already_fired_keeps_its_first_price(
    rollup_tables, rollup_writer
):
    alert_id = make_alert(rollup_tables)

    rollup_writer.mark_triggered(
        rollup_tables, [{"alert_id": alert_id, "price": 104.0}]
    )
    first = read_alert(rollup_tables, alert_id)

    rollup_writer.mark_triggered(
        rollup_tables, [{"alert_id": alert_id, "price": 999.0}]
    )
    second = read_alert(rollup_tables, alert_id)

    assert float(second.triggered_price) == 104.0
    assert second.triggered_at == first.triggered_at


def test_marking_nothing_writes_nothing(rollup_tables, rollup_writer):
    alert_id = make_alert(rollup_tables)

    marked = rollup_writer.mark_triggered(rollup_tables, [])

    assert marked == 0
    assert read_alert(rollup_tables, alert_id).triggered_at is None


def test_several_alerts_are_marked_in_one_go(rollup_tables, rollup_writer):
    first = make_alert(rollup_tables, symbol="NVDA")
    second = make_alert(
        rollup_tables, symbol="AMZN", direction="below", threshold=200.0
    )

    marked = rollup_writer.mark_triggered(
        rollup_tables,
        [
            {"alert_id": first, "price": 104.0},
            {"alert_id": second, "price": 198.0},
        ],
    )

    assert marked == 2
    assert float(read_alert(rollup_tables, first).triggered_price) == 104.0
    assert float(read_alert(rollup_tables, second).triggered_price) == 198.0


def test_the_read_the_check_and_the_write_fit_together(
    rollup_tables, rollup_db, rollup_writer, rollup_alerts
):
    alert_id = make_alert(rollup_tables)

    pending = rollup_db.read_pending_alerts(rollup_tables)
    fired = rollup_alerts.find_triggered(pending, {"NVDA": 104.0})
    marked = rollup_writer.mark_triggered(rollup_tables, fired)

    assert marked == 1
    assert float(read_alert(rollup_tables, alert_id).triggered_price) == 104.0
    assert rollup_db.read_pending_alerts(rollup_tables) == []
