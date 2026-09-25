"""The dashboard's HTTP calls into the api service.

The fakes below are the ones from tests/unit/test_market_status.py, extended
with a status_code and with post/delete recorders. No unittest.mock anywhere in
this repo: a fake that records what it was asked to do reads better than
assert_called_with, and it is the reason login() and delete_alert() take their
session, base URL and timeout as arguments rather than reading globals.
"""
import pytest
import requests

BASE_URL = "http://api:8000"
USERNAME = "ada"
PASSWORD = "correct-horse-battery-staple"
TOKEN = "header.payload.signature"
TIMEOUT = 10.0
ALERT_ID = 3


class FakeResponse:
    def __init__(self, status_code=200, payload=None, error=None):
        self.status_code = status_code
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    """Records the request it was asked to make, returns a canned response."""

    def __init__(self, response):
        self.response = response
        self.requests = []

    def post(self, url, json=None, timeout=None):
        self.requests.append(
            {"method": "POST", "url": url, "json": json, "timeout": timeout}
        )
        return self.response

    def delete(self, url, headers=None, timeout=None):
        self.requests.append(
            {"method": "DELETE", "url": url, "headers": headers, "timeout": timeout}
        )
        return self.response


def token_response(role="user"):
    return FakeResponse(payload={"access_token": TOKEN, "token_type": "bearer",
                                 "role": role})


def do_login(dashboard_auth, session, base_url=BASE_URL):
    return dashboard_auth.login(session, base_url, USERNAME, PASSWORD, TIMEOUT)


def do_delete(dashboard_auth, session, alert_id=ALERT_ID):
    return dashboard_auth.delete_alert(session, BASE_URL, TOKEN, alert_id, TIMEOUT)


def test_login_posts_the_username_and_password_to_the_login_path(dashboard_auth):
    session = FakeSession(token_response())

    do_login(dashboard_auth, session)

    sent = session.requests[0]
    assert sent["url"] == f"{BASE_URL}{dashboard_auth.LOGIN_PATH}"
    assert sent["json"] == {"username": USERNAME, "password": PASSWORD}


def test_login_sends_the_configured_timeout(dashboard_auth):
    """Without a timeout a hung api leaves the Streamlit page spinning forever,
    with nothing on screen to say why."""
    session = FakeSession(token_response())

    do_login(dashboard_auth, session)

    assert session.requests[0]["timeout"] == TIMEOUT


def test_login_returns_the_token_and_the_role(dashboard_auth):
    session = FakeSession(token_response(role="admin"))

    credentials = do_login(dashboard_auth, session)

    assert credentials.token == TOKEN
    assert credentials.role == "admin"


def test_wrong_credentials_raise_an_auth_error(dashboard_auth):
    """The 401 has to be recognised before raise_for_status() is reached.

    The fake carries an HTTPError as well, exactly as real requests would on a
    401, so this fails if the two are checked in the wrong order - and "wrong
    password" would surface to the user as an unhandled HTTP error.
    """
    session = FakeSession(
        FakeResponse(status_code=401, error=requests.HTTPError("401 Unauthorized"))
    )

    with pytest.raises(dashboard_auth.AuthError):
        do_login(dashboard_auth, session)


def test_a_server_failure_reaches_the_caller(dashboard_auth):
    """Not an AuthError. "Your password is wrong" is something the user can act
    on; "the api is down" is not, and dressing one up as the other sends them
    round a loop retyping a password that was always correct."""
    session = FakeSession(
        FakeResponse(status_code=500, error=requests.HTTPError("500 Server Error"))
    )

    with pytest.raises(requests.HTTPError):
        do_login(dashboard_auth, session)


def test_a_trailing_slash_on_the_base_url_is_tolerated(dashboard_auth):
    """API_BASE_URL comes from .env, where a trailing slash is easy to leave.
    Without rstrip the path becomes //auth/login, which some servers route and
    some answer 404 - a bug that only appears on someone else's machine."""
    session = FakeSession(token_response())

    do_login(dashboard_auth, session, base_url=f"{BASE_URL}/")

    assert session.requests[0]["url"] == f"{BASE_URL}{dashboard_auth.LOGIN_PATH}"


def test_deleting_an_alert_calls_the_alert_path_with_the_id(dashboard_auth):
    session = FakeSession(FakeResponse(status_code=204))

    do_delete(dashboard_auth, session, alert_id=42)

    expected = f"{BASE_URL}{dashboard_auth.ALERTS_PATH}/42"
    assert session.requests[0]["url"] == expected


def test_deleting_an_alert_sends_the_token_as_a_bearer_header(dashboard_auth):
    """Without this header the api answers 401 and the admin's delete button
    silently does nothing."""
    session = FakeSession(FakeResponse(status_code=204))

    do_delete(dashboard_auth, session)

    assert session.requests[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_a_deleted_alert_reports_success(dashboard_auth):
    session = FakeSession(FakeResponse(status_code=204))

    assert do_delete(dashboard_auth, session) is True


def test_an_alert_that_is_not_there_reports_failure(dashboard_auth):
    """False, not an exception. Someone else deleting the alert first is an
    ordinary race, and the page just re-renders without it."""
    session = FakeSession(FakeResponse(status_code=404))

    assert do_delete(dashboard_auth, session) is False


def test_a_forbidden_delete_raises_an_auth_error(dashboard_auth):
    """403 means the token is valid but this account is not an admin. An
    exception, because app.py has to say so rather than quietly redraw."""
    session = FakeSession(
        FakeResponse(status_code=403, error=requests.HTTPError("403 Forbidden"))
    )

    with pytest.raises(dashboard_auth.AuthError):
        do_delete(dashboard_auth, session)


def test_an_expired_token_on_delete_raises_an_auth_error(dashboard_auth):
    """401 here means the session died mid-visit. app.py catches AuthError,
    clears session_state and shows the login form again - which is why this
    cannot be a return value."""
    session = FakeSession(
        FakeResponse(status_code=401, error=requests.HTTPError("401 Unauthorized"))
    )

    with pytest.raises(dashboard_auth.AuthError):
        do_delete(dashboard_auth, session)


def do_register(dashboard_auth, session, base_url=BASE_URL):
    return dashboard_auth.register(session, base_url, USERNAME, PASSWORD, TIMEOUT)


def test_register_posts_the_username_and_password_to_the_register_path(dashboard_auth):
    session = FakeSession(
        FakeResponse(status_code=201, payload={"username": USERNAME, "role": "user"})
    )

    do_register(dashboard_auth, session)

    sent = session.requests[0]
    assert sent["url"] == f"{BASE_URL}{dashboard_auth.REGISTER_PATH}"
    assert sent["json"] == {"username": USERNAME, "password": PASSWORD}


def test_register_sends_the_configured_timeout(dashboard_auth):
    session = FakeSession(FakeResponse(status_code=201, payload={}))

    do_register(dashboard_auth, session)

    assert session.requests[0]["timeout"] == TIMEOUT


def test_a_created_account_reports_success(dashboard_auth):
    session = FakeSession(
        FakeResponse(status_code=201, payload={"username": USERNAME, "role": "user"})
    )

    assert do_register(dashboard_auth, session) is True


def test_a_username_that_is_taken_reports_failure(dashboard_auth):
    """False, not an exception, and not an AuthError.

    A taken username is not a credentials problem - nobody's session is wrong.
    It is an ordinary outcome the form can report so the person picks another
    name, which is the same shape as delete_alert's 404.
    """
    session = FakeSession(
        FakeResponse(status_code=409, error=requests.HTTPError("409 Conflict"))
    )

    assert do_register(dashboard_auth, session) is False


def test_a_server_failure_during_register_reaches_the_caller(dashboard_auth):
    session = FakeSession(
        FakeResponse(status_code=500, error=requests.HTTPError("500 Server Error"))
    )

    with pytest.raises(requests.HTTPError):
        do_register(dashboard_auth, session)


def test_a_forbidden_delete_reports_a_permission_problem(dashboard_auth):
    """403 gets its own type, because it needs different handling from 401.

    The delete control is shown to everyone, so a plain user pressing it is an
    ordinary thing to do. They are signed in correctly and must stay signed in
    - only the answer is no.
    """
    session = FakeSession(
        FakeResponse(status_code=403, error=requests.HTTPError("403 Forbidden"))
    )

    with pytest.raises(dashboard_auth.NotAllowedError):
        do_delete(dashboard_auth, session)


def test_an_expired_token_is_not_reported_as_a_permission_problem(dashboard_auth):
    """The other half: a 401 must NOT look like a permission problem, or the
    page would leave someone clicking a dead session forever."""
    session = FakeSession(
        FakeResponse(status_code=401, error=requests.HTTPError("401 Unauthorized"))
    )

    with pytest.raises(dashboard_auth.AuthError) as caught:
        do_delete(dashboard_auth, session)

    assert not isinstance(caught.value, dashboard_auth.NotAllowedError)
