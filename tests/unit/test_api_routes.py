from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clear_overrides(api_main):
    yield
    api_main.app.dependency_overrides.clear()

def make_client(api_main, rows=()):
    def fake_reader(symbol, hours):
        return list(rows)

    api_main.app.dependency_overrides[api_main.get_reader] = lambda: fake_reader

    return TestClient(api_main.app)

def make_recording_client(api_main):
    calls = []

    def record_readings(symbol, hours):
        calls.append((symbol, hours))
        return []

    api_main.app.dependency_overrides[api_main.get_reader] = lambda: record_readings

    return TestClient(api_main.app), calls

def test_health_returns_ok(api_main):
  client = TestClient(api_main.app)

  response = client.get("/health")

  assert response.status_code == 200
  assert response.json() == {"status": "ok"}

def test_candles_returns_the_serialised_rows(api_main, _candle_row):
    client = make_client(api_main, rows=[_candle_row()])

    response = client.get("/candles?symbol=NVDA")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "NVDA"
    assert body[0]["open"] == 100.0

def test_candles_with_no_rows_returns_an_empty_list(api_main):
    client = make_client(api_main, rows=[])

    response = client.get("/candles?symbol=NVDA")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 0

def test_the_symbol_is_upper_cased_before_the_lookup(api_main):
    client, calls = make_recording_client(api_main)

    client.get("/candles?symbol=nvda")

    assert calls[0][0] == "NVDA"

def test_a_missing_symbol_is_rejected(api_main):
    client, calls = make_recording_client(api_main)

    response = client.get("/candles")

    assert response.status_code == 422

def test_a_non_numeric_hours_is_rejected(api_main):
    client, calls = make_recording_client(api_main)

    response = client.get("/candles?symbol=nvda&hours=abc")

    assert response.status_code == 422

def test_hours_above_the_maximum_is_rejected(api_main):
    client, calls = make_recording_client(api_main)

    response = client.get("/candles?symbol=nvda&hours=999")

    assert response.status_code == 422

def test_hours_defaults_to_one_when_absent(api_main):
    client, calls = make_recording_client(api_main)

    client.get("/candles?symbol=nvda")

    assert calls[0][1] == 1


# ---------------------------------------------------------------- POST /auth/login

LOGIN_PATH = "/auth/login"
SECRET = "a-test-secret-that-is-long-enough-to-pass"
PASSWORD = "correct-horse-battery-staple"
TEST_ROUNDS = 4  # bcrypt is slow on purpose; see tests/unit/test_api_passwords.py


def make_user(api_passwords, username="ada", role="user", password=PASSWORD):
    """A stand-in for the row read_user hands back.

    SimpleNamespace rather than a dict, so the route has to reach for
    .password_hash exactly as it will against a real SQLAlchemy Row.
    """
    return SimpleNamespace(
        username=username,
        password_hash=api_passwords.hash_password(password, rounds=TEST_ROUNDS),
        role=role,
    )


def use_test_secret(api_main, api_config):
    """A real ApiConfig built from a dict, so the token is signed with a secret
    this file knows and can decode with."""
    api_main.app.dependency_overrides[api_main.get_config] = lambda: (
        api_config.load_config({"JWT_SECRET": SECRET})
    )


def make_login_client(api_main, api_config, user=None):
    """A client whose user lookup answers with `user` whatever it is asked.

    user=None is how "no such account" is expressed.
    """
    api_main.app.dependency_overrides[api_main.get_user_reader] = lambda: (
        lambda username: user
    )
    use_test_secret(api_main, api_config)

    return TestClient(api_main.app)


def make_recording_login_client(api_main, api_config, user=None):
    calls = []

    def record_lookup(username):
        calls.append(username)
        return user

    api_main.app.dependency_overrides[api_main.get_user_reader] = lambda: record_lookup
    use_test_secret(api_main, api_config)

    return TestClient(api_main.app), calls


def login(client, username="ada", password=PASSWORD):
    return client.post(LOGIN_PATH, json={"username": username, "password": password})


def test_a_correct_password_returns_a_token(api_main, api_config, api_passwords):
    client = make_login_client(api_main, api_config, make_user(api_passwords))

    response = login(client)

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_the_token_names_the_bearer_type(api_main, api_config, api_passwords):
    """The client has to know what to put in the Authorization header, and
    "bearer" is the word that goes in front of the token."""
    client = make_login_client(api_main, api_config, make_user(api_passwords))

    response = login(client)

    assert response.json()["token_type"] == "bearer"


def test_the_response_reports_the_users_role(api_main, api_config, api_passwords):
    """A display hint for the dashboard, so it can hide the delete control
    without shipping a JWT decoder. The API re-checks the claim on every
    privileged call and never trusts this coming back."""
    admin = make_user(api_passwords, role="admin")
    client = make_login_client(api_main, api_config, admin)

    response = login(client)

    assert response.json()["role"] == "admin"


def test_the_token_decodes_to_the_username_and_role(
    api_main, api_config, api_passwords, api_tokens
):
    """Not just that a token came back - that it says what it should. A route
    that signed the wrong claims would pass every test above this one."""
    admin = make_user(api_passwords, username="ada", role="admin")
    client = make_login_client(api_main, api_config, admin)

    token = login(client).json()["access_token"]

    claims = api_tokens.decode_token(SECRET, token)
    assert claims["sub"] == "ada"
    assert claims["role"] == "admin"


def test_a_wrong_password_is_rejected(api_main, api_config, api_passwords):
    client = make_login_client(api_main, api_config, make_user(api_passwords))

    response = login(client, password="not-the-password")

    assert response.status_code == 401


def test_an_unknown_username_is_rejected(api_main, api_config):
    client = make_login_client(api_main, api_config, user=None)

    response = login(client, username="nobody")

    assert response.status_code == 401


def test_an_unknown_username_and_a_wrong_password_are_answered_identically(
    api_main, api_config, api_passwords
):
    """No user enumeration.

    If the two failures differ in status or body by even a word, an attacker
    can discover which accounts exist by reading the difference - and knowing
    a username is real is most of the work of attacking it.
    """
    unknown = make_login_client(api_main, api_config, user=None)
    unknown_response = login(unknown, username="nobody")
    api_main.app.dependency_overrides.clear()

    wrong = make_login_client(api_main, api_config, make_user(api_passwords))
    wrong_response = login(wrong, password="not-the-password")

    assert unknown_response.status_code == wrong_response.status_code
    assert unknown_response.json() == wrong_response.json()


def test_the_username_is_lower_cased_before_the_lookup(api_main, api_config):
    """Postgres stores usernames case-sensitively - see
    tests/integration/test_api_users.py. Normalising here is what stops "Ada"
    and "ada" becoming two accounts nobody can tell apart."""
    client, calls = make_recording_login_client(api_main, api_config, user=None)

    login(client, username="ADA")

    assert calls[0] == "ada"


def test_the_password_hash_never_appears_in_the_response(
    api_main, api_config, api_passwords
):
    """Cheap, and it catches the easiest mistake in the file: returning the
    whole user row straight from the database."""
    user = make_user(api_passwords)
    client = make_login_client(api_main, api_config, user)

    response = login(client)

    assert user.password_hash not in response.text


def test_a_login_with_no_password_is_rejected(api_main, api_config):
    client = make_login_client(api_main, api_config, user=None)

    response = client.post(LOGIN_PATH, json={"username": "ada"})

    assert response.status_code == 422


def test_a_login_password_longer_than_seventy_two_bytes_is_rejected(
    api_main, api_config, api_passwords
):
    """422, not 500. bcrypt raises above 72 bytes rather than truncating, so
    without max_length on the model this would be an unhandled exception."""
    client = make_login_client(api_main, api_config, make_user(api_passwords))

    response = login(client, password="a" * 73)

    assert response.status_code == 422
