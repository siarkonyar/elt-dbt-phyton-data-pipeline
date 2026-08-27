from dataclasses import dataclass

import requests

MARKET_STATUS_PATH = "/stock/market-status"
DEFAULT_EXCHANGE = "US"


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    session: str

def build_session(api_key):
    """Reuses one TCP connection and keeps the key out of the URL."""
    session = requests.Session()
    session.headers.update({"X-Finnhub-Token": api_key})
    return session

def fetch_market_status(session, base_url, timeout_seconds, exchange=DEFAULT_EXCHANGE):
    """Raises on network or HTTP failure. The caller decides what that means."""
    response = session.get(
        f"{base_url}{MARKET_STATUS_PATH}",
        params={"exchange": exchange},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    return MarketStatus(
        is_open=bool(payload.get("isOpen")),
        session=payload.get("session"),
    )