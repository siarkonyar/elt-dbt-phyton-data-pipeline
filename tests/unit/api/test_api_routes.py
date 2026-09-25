import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clear_overrides(api_main):
    yield
    api_main.app.dependency_overrides.clear()

def stub_current_user(api_main, username="tester", role="user"):
    """Skip the whole auth layer for tests that are about something else.

    FastAPI resolves dependencies BEFORE it validates the endpoint's own query
    parameters, so an unauthenticated /candles with no symbol answers 401, not
    422 - which would quietly turn the query-validation tests below into auth
    tests that pass for the wrong reason. Overriding here keeps them about what
    they were written to check. Token-level behaviour has its own tests further
    down, and those use the real dependency.
    """
    api_main.app.dependency_overrides[api_main.get_current_user] = lambda: (
        api_main.AuthenticatedUser(username=username, role=role)
    )

def make_client(api_main, rows=()):
    def fake_reader(symbol, hours):
        return list(rows)

    api_main.app.dependency_overrides[api_main.get_reader] = lambda: fake_reader
    stub_current_user(api_main)

    return TestClient(api_main.app)

def make_recording_client(api_main):
    calls = []

    def record_readings(symbol, hours):
        calls.append((symbol, hours))
        return []

    api_main.app.dependency_overrides[api_main.get_reader] = lambda: record_readings
    stub_current_user(api_main)

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

# ------------------------------------------------- GET /candles, with real tokens

EXPIRES_IN = 3600
OTHER_SECRET = "a-different-secret-that-is-also-long-enough"


def issue_token(api_tokens, username="ada", role="user", now=None, secret=SECRET):
    return api_tokens.create_token(
        secret, username, role, now or datetime.now(UTC), EXPIRES_IN
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def unsigned_token(username="ada", role="user"):
    """The alg:none forgery, assembled by hand because PyJWT will not make one.

    See tests/unit/test_api_tokens.py for the same trick at the unit level; this
    one proves the route rejects it too, not just decode_token in isolation.
    """
    issued = int(datetime.now(UTC).timestamp())
    header = {"alg": "none", "typ": "JWT"}
    claims = {"sub": username, "role": role, "iat": issued, "exp": issued + EXPIRES_IN}
    encode = lambda part: (  # noqa: E731
        base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()
    )
    return f"{encode(header)}.{encode(claims)}."


def make_real_auth_client(api_main, api_config, rows=()):
    """Goes through the real get_current_user - no auth override at all.

    Only get_config is overridden, so the route verifies against a secret this
    file can sign with.
    """
    api_main.app.dependency_overrides[api_main.get_reader] = lambda: (
        lambda symbol, hours: list(rows)
    )
    use_test_secret(api_main, api_config)

    return TestClient(api_main.app)


def test_health_needs_no_token(api_main):
    """The compose stack and the e2e suite both hit this without credentials,
    and a health check that needs a token proves nothing about the container."""
    client = TestClient(api_main.app)

    assert client.get("/health").status_code == 200


def test_candles_without_a_token_is_rejected(api_main, api_config):
    client = make_real_auth_client(api_main, api_config)

    response = client.get("/candles?symbol=NVDA")

    assert response.status_code == 401


def test_candles_with_an_expired_token_is_rejected(api_main, api_config, api_tokens):
    """Issued two hours ago with a one-hour life, so it was already stale before
    the request was made."""
    client = make_real_auth_client(api_main, api_config)
    stale = issue_token(api_tokens, now=datetime.now(UTC) - timedelta(hours=2))

    response = client.get("/candles?symbol=NVDA", headers=bearer(stale))

    assert response.status_code == 401


def test_candles_with_a_token_signed_by_another_secret_is_rejected(
    api_main, api_config, api_tokens
):
    client = make_real_auth_client(api_main, api_config)
    forged = issue_token(api_tokens, secret=OTHER_SECRET)

    response = client.get("/candles?symbol=NVDA", headers=bearer(forged))

    assert response.status_code == 401


def test_candles_with_an_unsigned_token_is_rejected(api_main, api_config):
    """A token claiming alg:none, asking to be trusted with no signature."""
    client = make_real_auth_client(api_main, api_config)

    response = client.get("/candles?symbol=NVDA", headers=bearer(unsigned_token()))

    assert response.status_code == 401


def test_candles_with_a_header_missing_the_bearer_prefix_is_rejected(
    api_main, api_config, api_tokens
):
    """A perfectly good token, sent under the wrong scheme."""
    client = make_real_auth_client(api_main, api_config)
    token = issue_token(api_tokens)

    response = client.get(
        "/candles?symbol=NVDA", headers={"Authorization": f"Basic {token}"}
    )

    assert response.status_code == 401


def test_candles_with_a_malformed_authorization_header_is_rejected(
    api_main, api_config
):
    client = make_real_auth_client(api_main, api_config)

    response = client.get(
        "/candles?symbol=NVDA", headers={"Authorization": "Bearer one two"}
    )

    assert response.status_code == 401


def test_a_plain_user_may_read_the_candles(
    api_main, api_config, api_tokens, _candle_row
):
    """Reading is not an admin power. Without this, a require_admin accidentally
    placed on /candles would pass every rejection test above."""
    client = make_real_auth_client(api_main, api_config, rows=[_candle_row()])
    token = issue_token(api_tokens, role="user")

    response = client.get("/candles?symbol=NVDA", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "NVDA"


def test_the_rejection_names_the_bearer_scheme(api_main, api_config):
    """401 tells the client how to fix itself; that is the whole point of the
    header. 403 does not carry it, because there is nothing to retry."""
    client = make_real_auth_client(api_main, api_config)

    response = client.get("/candles?symbol=NVDA")

    assert response.headers["WWW-Authenticate"] == "Bearer"


# --------------------------------------------------------- POST /auth/register

REGISTER_PATH = "/auth/register"
NEW_USER_ID = 7


def make_register_client(api_main, api_config, created_id=NEW_USER_ID):
    """created_id=None is how "this username is taken" is expressed, which is
    exactly what db.create_user returns on an ON CONFLICT DO NOTHING."""
    calls = []

    def record_create(username, password_hash, role):
        calls.append({"username": username, "password_hash": password_hash,
                      "role": role})
        return created_id

    api_main.app.dependency_overrides[api_main.get_user_creator] = lambda: record_create
    use_test_secret(api_main, api_config)

    return TestClient(api_main.app), calls


def register(client, username="ada", password=PASSWORD, **extra):
    return client.post(
        REGISTER_PATH, json={"username": username, "password": password, **extra}
    )


def test_registering_creates_a_plain_user(api_main, api_config):
    client, calls = make_register_client(api_main, api_config)

    response = register(client)

    assert response.status_code == 201
    assert calls[0]["role"] == "user"


def test_a_registration_asking_for_the_admin_role_still_creates_a_plain_user(
    api_main, api_config
):
    """The test of this endpoint.

    The role must be hardcoded at the call site and never read from the body.
    Reading it is privilege escalation in one forgotten line, and it is how real
    systems get taken over.
    """
    client, calls = make_register_client(api_main, api_config)

    register(client, role="admin")

    assert calls[0]["role"] == "user"


def test_the_stored_password_is_a_hash_not_the_password(
    api_main, api_config, api_passwords
):
    client, calls = make_register_client(api_main, api_config)

    register(client)

    stored = calls[0]["password_hash"]
    assert stored != PASSWORD
    assert api_passwords.verify_password(PASSWORD, stored)


def test_the_username_is_lower_cased_before_it_is_stored(api_main, api_config):
    """Stored lower-cased for the same reason login looks up lower-cased - the
    two have to agree or the account is unreachable the moment it is made."""
    client, calls = make_register_client(api_main, api_config)

    register(client, username="ADA")

    assert calls[0]["username"] == "ada"


def test_a_username_that_is_already_taken_is_rejected(api_main, api_config):
    client, _ = make_register_client(api_main, api_config, created_id=None)

    response = register(client)

    assert response.status_code == 409


def test_a_registration_with_no_password_is_rejected(api_main, api_config):
    client, _ = make_register_client(api_main, api_config)

    response = client.post(REGISTER_PATH, json={"username": "ada"})

    assert response.status_code == 422


# ---------------------------------------------------- DELETE /alerts/{alert_id}

ALERT_ID = 3
MISSING_ALERT_ID = 9999


def make_delete_client(api_main, api_config, removed=1):
    """removed is the rowcount db.delete_alert hands back: 1 or 0."""
    calls = []

    def record_delete(alert_id):
        calls.append(alert_id)
        return removed

    api_main.app.dependency_overrides[api_main.get_alert_deleter] = (
        lambda: record_delete
    )
    use_test_secret(api_main, api_config)

    return TestClient(api_main.app), calls


def delete_alert(client, alert_id=ALERT_ID, headers=None):
    return client.delete(f"/alerts/{alert_id}", headers=headers or {})


def test_an_admin_deletes_an_alert(api_main, api_config, api_tokens):
    client, _ = make_delete_client(api_main, api_config)
    token = issue_token(api_tokens, role="admin")

    response = delete_alert(client, headers=bearer(token))

    assert response.status_code == 204


def test_the_alert_id_reaches_the_deleter(api_main, api_config, api_tokens):
    """The id from the URL, not a default. A route that ignored the path
    parameter would still answer 204 and delete the wrong row."""
    client, calls = make_delete_client(api_main, api_config)
    token = issue_token(api_tokens, role="admin")

    delete_alert(client, alert_id=42, headers=bearer(token))

    assert calls[0] == 42


def test_a_deleted_alert_returns_no_body(api_main, api_config, api_tokens):
    """204 means "done, nothing to say". A body with a 204 is a protocol
    violation some clients choke on."""
    client, _ = make_delete_client(api_main, api_config)
    token = issue_token(api_tokens, role="admin")

    response = delete_alert(client, headers=bearer(token))

    assert response.content == b""


def test_a_plain_user_may_not_delete_an_alert(api_main, api_config, api_tokens):
    """403, not 401. The token is perfectly valid - we know exactly who this is
    and the answer is still no."""
    client, calls = make_delete_client(api_main, api_config)
    token = issue_token(api_tokens, role="user")

    response = delete_alert(client, headers=bearer(token))

    assert response.status_code == 403
    assert calls == []


def test_a_request_with_no_token_may_not_delete_an_alert(api_main, api_config):
    client, calls = make_delete_client(api_main, api_config)

    response = delete_alert(client)

    assert response.status_code == 401
    assert calls == []


def test_a_token_claiming_an_unknown_role_may_not_delete_an_alert(
    api_main, api_config, api_tokens
):
    """Fail closed.

    The database CHECK constraint means no such row can exist, but the claim
    comes from a token, not the database. require_admin has to compare against
    "admin" - a check written as `!= "user"` would wave this straight through.
    """
    client, calls = make_delete_client(api_main, api_config)
    token = issue_token(api_tokens, role="superuser")

    response = delete_alert(client, headers=bearer(token))

    assert response.status_code == 403
    assert calls == []


def test_deleting_an_alert_that_is_not_there_is_a_not_found(
    api_main, api_config, api_tokens
):
    """The rowcount of 0 from db.delete_alert becomes a 404 here. That mapping
    is the route's job; the db layer keeps no opinion about HTTP."""
    client, _ = make_delete_client(api_main, api_config, removed=0)
    token = issue_token(api_tokens, role="admin")

    response = delete_alert(client, alert_id=MISSING_ALERT_ID, headers=bearer(token))

    assert response.status_code == 404


def test_an_alert_id_that_is_not_a_number_is_rejected(api_main, api_config, api_tokens):
    client, _ = make_delete_client(api_main, api_config)
    token = issue_token(api_tokens, role="admin")

    response = client.delete("/alerts/abc", headers=bearer(token))

    assert response.status_code == 422
