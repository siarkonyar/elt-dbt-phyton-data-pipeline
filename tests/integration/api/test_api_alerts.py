"""create_alert and read_alerts against a real Postgres.

The route only ever knows a username - that is all the token carries. These
check that the SQL turns it into the right user_id, and that a plain user's
list never leaks anyone else's alerts.
"""
from sqlalchemy import text

INSERT_USER_SQL = text(
    """
    INSERT INTO users (username, password_hash)
    VALUES (:username, '$2b$04$synthetic-value-for-tests-only')
    RETURNING user_id
    """
)

READ_OWNER_SQL = text("SELECT user_id FROM price_alerts WHERE alert_id = :alert_id")

COUNT_ALERTS_SQL = text("SELECT count(*) FROM price_alerts")


def make_user(connection, username):
    return connection.execute(INSERT_USER_SQL, {"username": username}).scalar_one()


def create(api_db, connection, username, symbol="NVDA", threshold=100.0):
    return api_db.create_alert(
        connection,
        username=username,
        symbol=symbol,
        direction="above",
        threshold=threshold,
    )


def test_a_new_alert_is_owned_by_the_user_named_in_the_token(api_tables, api_db):
    ada = make_user(api_tables, "ada")

    alert_id = create(api_db, api_tables, "ada")

    owner = api_tables.execute(READ_OWNER_SQL, {"alert_id": alert_id}).scalar_one()
    assert owner == ada


def test_an_alert_for_a_username_with_no_account_is_not_created(api_tables, api_db):
    """INSERT ... SELECT finds no user, so there is nothing to insert. None,
    not an exception, so the route decides what that means over HTTP."""
    assert create(api_db, api_tables, "nobody") is None

    assert api_tables.execute(COUNT_ALERTS_SQL).scalar_one() == 0


def test_a_user_reads_only_their_own_alerts(api_tables, api_db):
    make_user(api_tables, "ada")
    make_user(api_tables, "grace")
    mine = create(api_db, api_tables, "ada")
    create(api_db, api_tables, "grace")

    rows = api_db.read_alerts(api_tables, username="ada")

    assert [row.alert_id for row in rows] == [mine]


def test_an_admin_reads_everyones_alerts_with_the_owner_named(api_tables, api_db):
    make_user(api_tables, "ada")
    make_user(api_tables, "grace")
    create(api_db, api_tables, "ada")
    create(api_db, api_tables, "grace")

    rows = api_db.read_alerts(api_tables, username=None)

    assert sorted(row.username for row in rows) == ["ada", "grace"]


def test_alerts_come_back_newest_first(api_tables, api_db):
    """A user wants to see the alert they just added at the top."""
    make_user(api_tables, "ada")
    older = create(api_db, api_tables, "ada", symbol="NVDA")
    newer = create(api_db, api_tables, "ada", symbol="AMZN")

    rows = api_db.read_alerts(api_tables, username="ada")

    assert [row.alert_id for row in rows] == [newer, older]


def test_the_list_is_capped(api_tables, api_db):
    make_user(api_tables, "ada")
    for _ in range(api_db.ALERT_LIST_LIMIT + 1):
        create(api_db, api_tables, "ada")

    rows = api_db.read_alerts(api_tables, username="ada")

    assert len(rows) == api_db.ALERT_LIST_LIMIT
