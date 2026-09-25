"""The constraints on the users table, asserted against a real Postgres.

Everything here checks that the *database* refuses bad data, not that some
Python function does. A CHECK constraint holds even when a future code path
forgets to validate, which is the whole reason to spend a constraint on it.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

INSERT_SQL = text(
    "INSERT INTO users (username, password_hash, role) "
    "VALUES (:username, :password_hash, :role)"
)

# No role column, so the table's DEFAULT has to supply it.
INSERT_WITHOUT_ROLE_SQL = text(
    "INSERT INTO users (username, password_hash) VALUES (:username, :password_hash)"
)

READ_SQL = text("SELECT role, created_at FROM users WHERE username = :username")

# The column is plain TEXT with no format constraint, so this only has to look
# like a hash to a human reader.
PASSWORD_HASH = "$2b$04$synthetic-value-for-tests-only"


def insert_user(connection, username, role="user"):
    connection.execute(
        INSERT_SQL,
        {"username": username, "password_hash": PASSWORD_HASH, "role": role},
    )


def read_user(connection, username):
    return connection.execute(READ_SQL, {"username": username}).one()


def test_a_duplicate_username_is_refused_by_the_database(api_tables):
    """Two accounts with one name would make the login lookup ambiguous, so
    UNIQUE settles it before any application code has to."""
    insert_user(api_tables, "ada")

    with pytest.raises(IntegrityError):
        insert_user(api_tables, "ada")


def test_a_role_outside_admin_and_user_is_refused_by_the_database(api_tables):
    """A typo'd role must not become a third kind of user that no route knows
    how to authorise."""
    with pytest.raises(IntegrityError):
        insert_user(api_tables, "ada", role="superuser")


def test_a_user_with_no_role_defaults_to_user(api_tables):
    """The safe default. An INSERT that forgets the role creates the least
    privileged account, never an admin."""
    api_tables.execute(
        INSERT_WITHOUT_ROLE_SQL,
        {"username": "ada", "password_hash": PASSWORD_HASH},
    )

    assert read_user(api_tables, "ada").role == "user"


def test_a_new_user_is_stamped_with_a_created_at(api_tables):
    insert_user(api_tables, "grace")

    created_at = read_user(api_tables, "grace").created_at

    assert created_at is not None
    # Timezone-aware, which is what proves the column is TIMESTAMPTZ and not a
    # bare TIMESTAMP whose meaning depends on the server's local zone.
    assert created_at.tzinfo is not None
