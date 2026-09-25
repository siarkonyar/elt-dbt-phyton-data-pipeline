from dataclasses import dataclass

import requests

LOGIN_PATH = "/auth/login"
REGISTER_PATH = "/auth/register"
ALERTS_PATH = "/alerts"

UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
CONFLICT = 409


class AuthError(RuntimeError):
    """Raised when the credentials or the session are the problem.

    Deliberately not used for a dead api or a 500. Those are not something the
    person at the keyboard can fix, and telling them their password was wrong
    sends them round a loop retyping one that was always correct.
    """


class NotAllowedError(AuthError):
    """403: we know exactly who you are, and the answer is still no.

    A subclass, so anything catching AuthError still catches this. It exists
    because 401 and 403 need opposite handling: a 401 means the session is dead
    and the page must sign you out, while a 403 means you are signed in
    perfectly well and simply may not do this. Signing out on a 403 would throw
    a plain user back to the login form for pressing a button they can see.
    """


@dataclass(frozen=True)
class Credentials:
    token: str
    role: str


def build_session():
    """One session, so repeated calls reuse the same TCP connection.

    No headers set here, unlike market_status.build_session: the token changes
    with each login, so it travels per request instead.
    """
    return requests.Session()


def _url(base_url, path):
    """rstrip because API_BASE_URL comes from .env, where a trailing slash is
    easy to leave behind. Without it the path becomes //auth/login, which some
    servers route and others answer 404 - a bug that only ever shows up on
    someone else's machine."""
    return f"{base_url.rstrip('/')}{path}"


def login(session, base_url, username, password, timeout_seconds):
    response = session.post(
        _url(base_url, LOGIN_PATH),
        json={"username": username, "password": password},
        timeout=timeout_seconds,
    )

    if response.status_code == UNAUTHORIZED:
        raise AuthError("Wrong username or password.")

    response.raise_for_status()
    payload = response.json()

    # The api calls it access_token; this dataclass calls it token.
    return Credentials(token=payload["access_token"], role=payload["role"])


def register(session, base_url, username, password, timeout_seconds):
    """True if the account was created, False if the username was taken.

    No token comes back and none is sent: registering is not signing in. The
    caller creates the account, then logs in like anyone else.

    A taken username is not an AuthError - nobody's credentials or session are
    wrong. It is an ordinary outcome the form reports so the person picks
    another name, the same shape as delete_alert's 404.

    The api decides the role, and it is always a plain user. Nothing here can
    ask for anything else.
    """
    response = session.post(
        _url(base_url, REGISTER_PATH),
        json={"username": username, "password": password},
        timeout=timeout_seconds,
    )

    if response.status_code == CONFLICT:
        return False

    response.raise_for_status()
    return True


def delete_alert(session, base_url, token, alert_id, timeout_seconds):
    response = session.delete(
        _url(base_url, f"{ALERTS_PATH}/{alert_id}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout_seconds,
    )

    # Two separate checks, not one combined branch: the page reacts to these
    # differently, so they cannot arrive as the same exception.
    if response.status_code == FORBIDDEN:
        raise NotAllowedError("Only an admin can delete an alert.")

    if response.status_code == UNAUTHORIZED:
        raise AuthError("Your session has expired.")

    # Not an error: someone else may have deleted it first. The page just
    # re-renders without it.
    if response.status_code == NOT_FOUND:
        return False

    response.raise_for_status()
    return True
