"""prepare_database - what a fresh container does before it serves anything.

prepare_database takes a connection rather than an engine precisely so these
tests can drive it on the rollback fixture: the table it creates and the admin
it seeds both disappear when the test ends.
"""
from sqlalchemy import text

SECRET = "a-test-secret-that-is-long-enough-to-pass"
ADMIN_PASSWORD = "an-admin-password"

COUNT_USERS_SQL = text("SELECT count(*) FROM users")
TABLES_SQL = text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")


def seeded_config(api_config, username="admin", password=ADMIN_PASSWORD):
    return api_config.load_config(
        {
            "JWT_SECRET": SECRET,
            "API_ADMIN_USERNAME": username,
            "API_ADMIN_PASSWORD": password,
        }
    )


def bare_config(api_config):
    """Valid settings with no admin configured - seeding nothing is allowed."""
    return api_config.load_config({"JWT_SECRET": SECRET})


def count_users(connection):
    return connection.execute(COUNT_USERS_SQL).scalar()


def test_the_startup_creates_the_users_table(connection, api_main, api_config):
    api_main.prepare_database(connection, bare_config(api_config))

    tables = connection.execute(TABLES_SQL).scalars().all()

    assert "users" in tables


def test_the_startup_seeds_the_configured_admin(
    connection, api_main, api_config, api_db
):
    api_main.prepare_database(connection, seeded_config(api_config))

    assert api_db.read_user(connection, "admin") is not None


def test_the_seeded_admin_has_the_admin_role(connection, api_main, api_config, api_db):
    """The one account that can delete an alert. If this came out as a plain
    user, a fresh install would have no way to reach the admin route at all."""
    api_main.prepare_database(connection, seeded_config(api_config))

    assert api_db.read_user(connection, "admin").role == "admin"


def test_the_seeded_admin_password_verifies(
    connection, api_main, api_config, api_db, api_passwords
):
    """Hashed on the way in, not stored raw."""
    api_main.prepare_database(connection, seeded_config(api_config))

    stored = api_db.read_user(connection, "admin").password_hash

    assert stored != ADMIN_PASSWORD
    assert api_passwords.verify_password(ADMIN_PASSWORD, stored)


def test_the_seeded_admin_username_is_lower_cased(
    connection, api_main, api_config, api_db
):
    """API_ADMIN_USERNAME=Admin in .env has to become "admin" in the table.

    login() lower-cases before it looks up, and Postgres stores usernames
    case-sensitively. Seed "Admin" without normalising and the account exists
    but nobody can ever log into it - which reads as a wrong password, with
    nothing in any log to say otherwise.
    """
    api_main.prepare_database(connection, seeded_config(api_config, username="Admin"))

    assert api_db.read_user(connection, "admin") is not None


def test_running_the_startup_twice_leaves_one_admin(connection, api_main, api_config):
    """Every container restart runs this again. The second pass has to be a
    no-op, which is what ON CONFLICT DO NOTHING buys."""
    config = seeded_config(api_config)

    api_main.prepare_database(connection, config)
    api_main.prepare_database(connection, config)

    assert count_users(connection) == 1


def test_running_the_startup_twice_does_not_change_the_password_hash(
    connection, api_main, api_config, api_db
):
    """The test that catches DO UPDATE.

    With DO UPDATE the test above still passes - one row, right username - while
    every restart silently resets a password the admin had changed.
    """
    config = seeded_config(api_config)
    api_main.prepare_database(connection, config)
    first = api_db.read_user(connection, "admin").password_hash

    api_main.prepare_database(connection, config)

    assert api_db.read_user(connection, "admin").password_hash == first


def test_no_admin_is_seeded_when_none_is_configured(connection, api_main, api_config):
    """A fresh install with no credentials in .env gets no accounts at all.

    Safe, and visible: zero admins is obvious the first time someone tries to
    log in. A default password would be neither.
    """
    api_main.prepare_database(connection, bare_config(api_config))

    assert count_users(connection) == 0
