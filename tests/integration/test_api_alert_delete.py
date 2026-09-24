"""delete_alert against a real Postgres.

price_alerts belongs to the rollup service's schema, so these use
rollup_tables. The api service reads and deletes from a table it does not own -
deliberate, and the reason the fixture here is not api_tables.

Helpers are local, matching tests/integration/test_alert_writer.py rather than
adding more conftest fixtures.
"""
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

# BIGSERIAL starts at 1 and the rollback fixture never lets a test see another
# test's rows, so nothing will ever own this id.
MISSING_ALERT_ID = 9999


def make_alert(connection, symbol="NVDA", direction="above", threshold=100.0):
    """Put one waiting alert in the table and hand back its id."""
    return connection.execute(
        INSERT_ALERT_SQL,
        {"symbol": symbol, "direction": direction, "threshold": threshold},
    ).scalar_one()


def fire_alert(connection, alert_id, price=104.0):
    connection.execute(FIRE_ALERT_SQL, {"alert_id": alert_id, "price": price})


def read_alert(connection, alert_id):
    """one_or_none, so a deleted alert reads as None instead of raising."""
    return connection.execute(READ_ALERT_SQL, {"alert_id": alert_id}).one_or_none()


def test_deleting_an_alert_removes_the_row(rollup_tables, api_db):
    alert_id = make_alert(rollup_tables)

    api_db.delete_alert(rollup_tables, alert_id)

    assert read_alert(rollup_tables, alert_id) is None


def test_deleting_an_alert_reports_one_row_gone(rollup_tables, api_db):
    alert_id = make_alert(rollup_tables)

    removed = api_db.delete_alert(rollup_tables, alert_id)

    assert removed == 1


def test_deleting_an_alert_that_is_not_there_reports_nothing_gone(
    rollup_tables, api_db
):
    """Zero, not an exception.

    In SQL a DELETE against an id that is not there succeeds and affects no
    rows. Returning the count is what lets the route turn 0 into a 404 and
    anything else into a 204, while this layer keeps no opinion about HTTP.
    """
    removed = api_db.delete_alert(rollup_tables, MISSING_ALERT_ID)

    assert removed == 0


def test_deleting_one_alert_leaves_the_others_alone(rollup_tables, api_db):
    """The WHERE clause has to be bound to the id. A missing or mistyped
    parameter would empty the whole table and still pass the first two tests."""
    doomed = make_alert(rollup_tables, symbol="NVDA")
    spared = make_alert(rollup_tables, symbol="AMZN")

    api_db.delete_alert(rollup_tables, doomed)

    assert read_alert(rollup_tables, spared) is not None


def test_deleting_an_alert_that_already_fired_still_removes_it(rollup_tables, api_db):
    """A fired alert keeps triggered_at and triggered_price as a record of what
    happened, but it is still an ordinary row to delete. The WHERE clause keys
    on alert_id alone - it must not also filter on triggered_at IS NULL.
    """
    alert_id = make_alert(rollup_tables)
    fire_alert(rollup_tables, alert_id)

    removed = api_db.delete_alert(rollup_tables, alert_id)

    assert removed == 1
    assert read_alert(rollup_tables, alert_id) is None
