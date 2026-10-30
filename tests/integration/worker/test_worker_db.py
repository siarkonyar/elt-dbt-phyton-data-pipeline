"""The worker's queries against a real Postgres.

Reading an alert needs the api's tables (users, price_alerts), so those tests
use api_tables. Recording a send needs only the worker's own
notification_history, which has no foreign key, so those use worker_tables.
"""
from datetime import UTC, datetime

from sqlalchemy import text

FIRED_AT = datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC)

INSERT_USER_SQL = text(
    """
    INSERT INTO users (email, password_hash)
    VALUES ('ada@example.com', '$2b$04$synthetic-value-for-tests-only')
    RETURNING user_id
    """
)

INSERT_ALERT_SQL = text(
    """
    INSERT INTO price_alerts
        (user_id, symbol, direction, threshold, triggered_at, triggered_price)
    VALUES (:user_id, 'NVDA', 'above', 100.0, :triggered_at, :triggered_price)
    RETURNING alert_id
    """
)

READ_HISTORY_SQL = text(
    """
    SELECT status, message_id, error, attempted_at
      FROM notification_history
     WHERE alert_id = :alert_id
     ORDER BY notification_id
    """
)


def make_alert(connection, fired=True):
    user_id = connection.execute(INSERT_USER_SQL).scalar_one()
    return connection.execute(
        INSERT_ALERT_SQL,
        {
            "user_id": user_id,
            "triggered_at": FIRED_AT if fired else None,
            "triggered_price": 102.0 if fired else None,
        },
    ).scalar_one()


def read_history(connection, alert_id):
    return connection.execute(READ_HISTORY_SQL, {"alert_id": alert_id}).all()


def test_a_fired_alert_comes_back_with_its_owners_email(api_tables, worker_db):
    alert_id = make_alert(api_tables)

    alert = worker_db.read_alert_to_email(api_tables, alert_id)

    assert alert.email == "ada@example.com"
    assert alert.symbol == "NVDA"
    assert alert.direction == "above"
    assert float(alert.triggered_price) == 102.0
    assert alert.triggered_at == FIRED_AT


def test_an_alert_that_has_not_fired_comes_back_as_none(api_tables, worker_db):
    alert_id = make_alert(api_tables, fired=False)

    assert worker_db.read_alert_to_email(api_tables, alert_id) is None


def test_a_deleted_alert_comes_back_as_none(api_tables, worker_db):
    assert worker_db.read_alert_to_email(api_tables, 999_999) is None


def test_a_sent_email_is_recorded_with_its_message_id(worker_tables, worker_db):
    worker_db.record_notification(
        worker_tables, 7, {"success": True, "message_id": "msg_1"}
    )

    [row] = read_history(worker_tables, 7)
    assert (row.status, row.message_id, row.error) == ("sent", "msg_1", None)
    assert row.attempted_at is not None


def test_a_failed_email_is_recorded_with_its_error(worker_tables, worker_db):
    worker_db.record_notification(
        worker_tables, 7, {"success": False, "error": "Resend is down"}
    )

    [row] = read_history(worker_tables, 7)
    assert (row.status, row.message_id, row.error) == (
        "failed",
        None,
        "Resend is down",
    )


def test_every_attempt_gets_its_own_row(worker_tables, worker_db):
    """A retried email shows each try, not just the last one."""
    worker_db.record_notification(
        worker_tables, 7, {"success": False, "error": "Resend is down"}
    )
    worker_db.record_notification(
        worker_tables, 7, {"success": True, "message_id": "msg_1"}
    )

    statuses = [row.status for row in read_history(worker_tables, 7)]
    assert statuses == ["failed", "sent"]
