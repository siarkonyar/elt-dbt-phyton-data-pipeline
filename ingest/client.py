import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

import requests

# Worth another attempt: the server is busy, or we are going too fast.
# Everything else (401 bad key, 403 no access) means the request is wrong.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

BACKOFF_BASE_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 120.0
USER_AGENT = "siar-elt-ingest/1.0"

US_EXCHANGE = "US"


class FinnhubApiError(RuntimeError):
    """Raised when Finnhub cannot be reached or answers with something unusable."""

def build_session(api_key):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "X-Finnhub-Token": api_key,
        }
    )
    return session

@dataclass(frozen=True)
class Quote:
    symbol: str
    quote_ts: datetime
    price: float
    day_open: float
    day_high: float
    day_low: float
    previous_close: float
    change: float
    pct_change: float
    source_url: str


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    session: str
    holiday: str

def retry_after_seconds(response):
    """Honour Retry-After when the server sends it. None means 'use backoff'."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    try:
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(raw)))
    except ValueError:
        # The spec also allows an HTTP date. Not worth parsing -- back off instead.
        return None


def backoff_with_jitter(attempt, random_func=random.random):
    """Exponential backoff, randomised so retries do not land in lockstep."""
    ceiling = BACKOFF_BASE_SECONDS * 2**attempt
    return random_func() * ceiling

def to_utc(epoch_seconds):
    """Unix seconds -> a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)


def parse_quote(payload, symbol, url):
    price = payload.get("c")
    quote_ts = payload.get("t")

    # An unknown symbol comes back as HTTP 200 with every field zeroed, which
    # would otherwise store a $0 stock priced at 1970-01-01.
    if not price or not quote_ts:
        raise FinnhubApiError(
            f"{url} returned no usable quote for {symbol!r} "
            f"(price={price!r}, t={quote_ts!r}) -- is the symbol real?"
        )

    return Quote(
        symbol=symbol,
        quote_ts=to_utc(quote_ts),
        price=price,
        day_open=payload.get("o"),
        day_high=payload.get("h"),
        day_low=payload.get("l"),
        previous_close=payload.get("pc"),
        change=payload.get("d"),
        pct_change=payload.get("dp"),
        source_url=url,
    )

@dataclass
class FinnhubClient:
    session: Any
    api_key: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    bucket: Any
    breaker: Any
    sleep: Callable = time.sleep
    requests_made: int = 0
    retries: int = 0
    throttled_seconds: float = 0.0

    def reset_stats(self):
        self.requests_made = 0
        self.retries = 0
        self.throttled_seconds = 0.0

    def _get(self, path, params):
        """GET a JSON document through the rate limiter and the breaker."""
        url = f"{self.base_url}/{path}?{urlencode(params)}"
        self.breaker.before_request()

        last_problem = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                self.retries += 1

            self.throttled_seconds += self.bucket.acquire()
            self.requests_made += 1
            wait = None

            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as error:
                last_problem = f"{type(error).__name__}: {error}"
            else:
                if response.status_code == 200:
                    self.breaker.record_success()
                    try:
                        return response.json(), url
                    except ValueError as error:
                        raise FinnhubApiError(
                            f"{url} returned HTTP 200 but the body is not JSON: "
                            f"{response.text[:200]}"
                        ) from error

                if response.status_code not in RETRY_STATUS_CODES:
                    # Our mistake (bad key, no access) -- do not trip the breaker.
                    raise FinnhubApiError(
                        f"{url} returned HTTP {response.status_code}, "
                        f"which will not change on a retry: {response.text[:200]}"
                    )

                last_problem = f"HTTP {response.status_code}: {response.text[:200]}"
                wait = retry_after_seconds(response)

            if attempt < self.max_retries:
                self.sleep(wait if wait is not None else backoff_with_jitter(attempt))

        self.breaker.record_failure()
        raise FinnhubApiError(
            f"{url} failed {self.max_retries + 1} times. Last problem: {last_problem}"
        )

    def fetch_quote(self, symbol):
        payload, url = self._get("quote", {"symbol": symbol})
        return parse_quote(payload, symbol, url)

    def fetch_market_status(self, exchange=US_EXCHANGE):
        payload, url = self._get("stock/market-status", {"exchange": exchange})

        if payload.get("isOpen") is None:
            raise FinnhubApiError(f"{url} returned no isOpen field: {payload}")

        return MarketStatus(
            is_open=bool(payload["isOpen"]),
            session=payload.get("session"),
            holiday=payload.get("holiday"),
        )