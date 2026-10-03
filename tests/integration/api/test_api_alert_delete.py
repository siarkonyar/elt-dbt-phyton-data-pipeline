"""delete_alert against a real Postgres.

price_alerts belongs to the api service's schema, so these use api_tables.
Every alert needs an owner now, so each test makes a user first.

Helpers are local rather than more conftest fixtures.
"""
from sqlalchemy import text

INSERT_USER_SQL = text(
    """
    INSERT INTO users (email, password_hash)
    VALUES (:email, :password_hash)
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

FIRE_ALERT_SQL = text(
    """
    UPDATE price_alerts
      SET triggered_at = now(), triggered_price = :price
    WHERE alert_id = :alert_id
    """
)

READ_ALERT_SQL = text("SELECT * FROM price_alerts WHERE alert_id = :alert_id")

PASSWORD_HASH = "$2b$04$synthetic-value-for-tests-only"

# BIGSERIAL starts at 1 and the rollback fixture never lets a test see another
# test's rows, so nothing will ever own this id.
MISSING_ALERT_ID = 9999


def make_user(connection, email="ada@example.com"):
    return connection.execute(
        INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH}
    ).scalar_one()


def make_alert(connection, user_id, symbol="NVDA", direction="above", threshold=100.0):
    """Put one waiting alert in the table and hand back its id."""
    return connection.execute(
        INSERT_ALERT_SQL,
        {
            "user_id": user_id,
            "symbol": symbol,
            "direction": direction,
            "threshold": threshold,
        },
    ).scalar_one()


def fire_alert(connection, alert_id, price=104.0):
    connection.execute(FIRE_ALERT_SQL, {"alert_id": alert_id, "price": price})


def read_alert(connection, alert_id):
    """one_or_none, so a deleted alert reads as None instead of raising."""
    return connection.execute(READ_ALERT_SQL, {"alert_id": alert_id}).one_or_none()


def test_deleting_an_alert_removes_the_row(api_tables, api_db):
    alert_id = make_alert(api_tables, make_user(api_tables))

    api_db.delete_alert(api_tables, alert_id)

    assert read_alert(api_tables, alert_id) is None


def test_deleting_an_alert_reports_one_row_gone(api_tables, api_db):
    alert_id = make_alert(api_tables, make_user(api_tables))

    removed = api_db.delete_alert(api_tables, alert_id)

    assert removed == 1


def test_deleting_an_alert_that_is_not_there_reports_nothing_gone(
    api_tables, api_db
):
    """Zero, not an exception.

    In SQL a DELETE against an id that is not there succeeds and affects no
    rows. Returning the count is what lets the route turn 0 into a 404 and
    anything else into a 204, while this layer keeps no opinion about HTTP.
    """
    removed = api_db.delete_alert(api_tables, MISSING_ALERT_ID)

    assert removed == 0


def test_deleting_one_alert_leaves_the_others_alone(api_tables, api_db):
    """The WHERE clause has to be bound to the id. A missing or mistyped
    parameter would empty the whole table and still pass the first two tests."""
    user_id = make_user(api_tables)
    doomed = make_alert(api_tables, user_id, symbol="NVDA")
    spared = make_alert(api_tables, user_id, symbol="AMZN")

    api_db.delete_alert(api_tables, doomed)

    assert read_alert(api_tables, spared) is not None


def test_deleting_an_alert_that_already_fired_still_removes_it(api_tables, api_db):
    """A fired alert keeps triggered_at and triggered_price as a record of what
    happened, but it is still an ordinary row to delete. The WHERE clause keys
    on alert_id alone - it must not also filter on triggered_at IS NULL.
    """
    alert_id = make_alert(api_tables, make_user(api_tables))
    fire_alert(api_tables, alert_id)

    removed = api_db.delete_alert(api_tables, alert_id)

    assert removed == 1
    assert read_alert(api_tables, alert_id) is None
