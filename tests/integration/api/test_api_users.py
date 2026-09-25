"""read_user and create_user against a real Postgres.

These drive the two behaviours the whole seeding story rests on: creating the
same username twice is a no-op rather than an error, and the second attempt
leaves the first row exactly as it was.
"""
PASSWORD = "correct-horse-battery-staple"
TEST_ROUNDS = 4  # see tests/unit/test_api_passwords.py - bcrypt is slow on purpose


def test_a_created_user_can_be_read_back(api_tables, api_db):
    api_db.create_user(api_tables, "ada", "a-hash", "user")

    user = api_db.read_user(api_tables, "ada")

    assert user.username == "ada"


def test_the_role_comes_back_with_the_user(api_tables, api_db):
    api_db.create_user(api_tables, "ada", "a-hash", "admin")

    user = api_db.read_user(api_tables, "ada")

    assert user.role == "admin"


def test_an_unknown_username_reads_as_none(api_tables, api_db):
    """None, not an exception. A failed login is an ordinary event, and the
    route needs to answer 401 rather than 500."""
    assert api_db.read_user(api_tables, "nobody") is None


def test_creating_the_same_username_twice_does_not_raise(api_tables, api_db):
    """ON CONFLICT DO NOTHING rather than an IntegrityError. Startup seeding
    runs on every container restart and has to be a no-op the second time.

    The return value is what tells the two apart, which is what POST
    /auth/register later turns into a 409.
    """
    first = api_db.create_user(api_tables, "ada", "a-hash", "admin")
    second = api_db.create_user(api_tables, "ada", "another-hash", "admin")

    assert first is not None
    assert second is None


def test_the_second_create_leaves_the_first_password_hash_alone(api_tables, api_db):
    """DO NOTHING, never DO UPDATE.

    With DO UPDATE this test still passes a casual reading - a row exists and
    the username is right - while every container restart silently resets a
    password the user had changed.
    """
    api_db.create_user(api_tables, "ada", "the-original-hash", "admin")
    api_db.create_user(api_tables, "ada", "a-replacement-hash", "admin")

    stored = api_db.read_user(api_tables, "ada").password_hash

    assert stored == "the-original-hash"


def test_the_stored_hash_verifies_against_the_password(
    api_tables, api_db, api_passwords
):
    """The round trip that matters: a hash survives Postgres unchanged. A TEXT
    column that trimmed or re-encoded it would leave every login failing."""
    hashed = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)
    api_db.create_user(api_tables, "ada", hashed, "user")

    stored = api_db.read_user(api_tables, "ada").password_hash

    assert api_passwords.verify_password(PASSWORD, stored)


def test_the_database_lookup_is_case_sensitive(api_tables, api_db):
    """Postgres treats "Ada" and "ada" as two different usernames.

    Nothing here is wrong, and this test is not asking for it to change. It
    pins the behaviour down, because it is the reason the API lower-cases
    every username before it ever reaches this layer - and the reason the
    seeded admin must be lower-cased too.
    """
    api_db.create_user(api_tables, "ada", "a-hash", "user")

    assert api_db.read_user(api_tables, "Ada") is None
