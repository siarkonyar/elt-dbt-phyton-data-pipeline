"""The constraints on the price_alerts table, asserted against a real Postgres.

The api owns this table now, so it is created by the api's schema.sql next to
users. Every alert belongs to the user who created it, and these tests check
that the *database* enforces that, not some Python function.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

INSERT_USER_SQL = text(
    "INSERT INTO users (email, password_hash) "
    "VALUES (:email, :password_hash) "
    "RETURNING user_id"
)

INSERT_ALERT_SQL = text(
    "INSERT INTO price_alerts (user_id, symbol, direction, threshold) "
    "VALUES (:user_id, :symbol, :direction, :threshold) "
    "RETURNING alert_id"
)

READ_ALERT_SQL = text("SELECT user_id FROM price_alerts WHERE alert_id = :alert_id")

PASSWORD_HASH = "$2b$04$synthetic-value-for-tests-only"

# BIGSERIAL starts at 1, and every test runs inside a rolled-back transaction,
# so no real user can ever have this id.
MISSING_USER_ID = 999_999


def insert_user(connection, email):
    return connection.execute(
        INSERT_USER_SQL, {"email": email, "password_hash": PASSWORD_HASH}
    ).scalar_one()


def insert_alert(connection, user_id):
    return connection.execute(
        INSERT_ALERT_SQL,
        {"user_id": user_id, "symbol": "NVDA", "direction": "above", "threshold": 100},
    ).scalar_one()


def test_an_alert_for_a_user_that_does_not_exist_is_refused(api_tables):
    """The foreign key's whole job. An alert pointing at nobody would be an
    alert no one can ever see or delete as their own."""
    with pytest.raises(IntegrityError):
        insert_alert(api_tables, MISSING_USER_ID)


def test_an_alert_with_no_user_is_refused(api_tables):
    """A foreign key on its own lets NULL through. NOT NULL is what makes an
    owner compulsory rather than optional."""
    with pytest.raises(IntegrityError):
        insert_alert(api_tables, None)


def test_an_alert_is_stored_against_the_user_who_created_it(api_tables):
    user_id = insert_user(api_tables, "ada@example.com")

    alert_id = insert_alert(api_tables, user_id)

    stored = api_tables.execute(READ_ALERT_SQL, {"alert_id": alert_id}).one()
    assert stored.user_id == user_id
