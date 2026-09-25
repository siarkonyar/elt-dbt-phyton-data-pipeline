from dataclasses import dataclass

import requests

LOGIN_PATH = "/auth/login"
ALERTS_PATH = "/alerts"

UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404


class AuthError(RuntimeError):
    """Raised when the credentials or the session are the problem.

    Deliberately not used for a dead api or a 500. Those are not something the
    person at the keyboard can fix, and telling them their password was wrong
    sends them round a loop retyping one that was always correct.
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


def delete_alert(session, base_url, token, alert_id, timeout_seconds):
    response = session.delete(
        _url(base_url, f"{ALERTS_PATH}/{alert_id}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout_seconds,
    )

    if response.status_code in (UNAUTHORIZED, FORBIDDEN):
        raise AuthError("Your session has expired, or this account is not an admin.")

    # Not an error: someone else may have deleted it first. The page just
    # re-renders without it.
    if response.status_code == NOT_FOUND:
        return False

    response.raise_for_status()
    return True
