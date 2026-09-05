import pytest
import requests

from market_status import (
    MARKET_STATUS_PATH,
    build_session,
    fetch_market_status,
)

BASE_URL = "https://finnhub.io/api/v1"


class FakeResponse:
    def __init__(self, payload=None, error=None):
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

    def get(self, url, params=None, timeout=None):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        return self.response


def test_reads_is_open_and_session_from_the_payload():
    # Arrange
    session = FakeSession(FakeResponse({"isOpen": True, "session": "regular"}))

    # Act
    status = fetch_market_status(session, BASE_URL, timeout_seconds=10)

    # Assert
    assert status.is_open is True
    assert status.session == "regular"


def test_missing_is_open_counts_as_closed():
    session = FakeSession(FakeResponse({"session": "pre-market"}))

    status = fetch_market_status(session, BASE_URL, timeout_seconds=10)

    assert status.is_open is False


def test_missing_session_becomes_none():
    session = FakeSession(FakeResponse({"isOpen": False}))

    status = fetch_market_status(session, BASE_URL, timeout_seconds=10)

    assert status.session is None


def test_http_errors_reach_the_caller():
    session = FakeSession(FakeResponse(error=requests.HTTPError("429 Too Many Requests")))

    with pytest.raises(requests.HTTPError):
        fetch_market_status(session, BASE_URL, timeout_seconds=10)


def test_requests_the_market_status_path_with_the_exchange_and_timeout():
    session = FakeSession(FakeResponse({"isOpen": True, "session": "regular"}))

    fetch_market_status(session, BASE_URL, timeout_seconds=7)

    assert session.requests == [
        {
            "url": f"{BASE_URL}{MARKET_STATUS_PATH}",
            "params": {"exchange": "US"},
            "timeout": 7,
        }
    ]


def test_exchange_can_be_overridden():
    session = FakeSession(FakeResponse({"isOpen": False, "session": None}))

    fetch_market_status(session, BASE_URL, timeout_seconds=10, exchange="L")

    assert session.requests[0]["params"] == {"exchange": "L"}


def test_build_session_puts_the_api_key_in_a_header_not_the_url():
    session = build_session("secret-key")

    assert session.headers["X-Finnhub-Token"] == "secret-key"