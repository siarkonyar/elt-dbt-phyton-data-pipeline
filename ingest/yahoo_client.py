import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote as urlquote, urlencode
import random
import requests

# Worth another attempt: the server is busy, or we are going too fast.
# Everything else (401, 404) means the request itself is wrong.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

BACKOFF_BASE_SECONDS = 1.0
USER_AGENT = "siar-elt-ingest/1.0"

# Must stay "1d". chartPreviousClose means "the close before the chart
# window", so it is only yesterday's close while the window is one day.
CHART_RANGE = "1d"
CHART_INTERVAL = "1d"


class YahooApiError(RuntimeError):
    """Raised when Yahoo cannot be reached or answers with something unusable."""

@dataclass(frozen=True)
class Quote:
    symbol: str
    quote_ts: datetime
    price: float
    previous_close: float
    day_high: float
    day_low: float
    volume: int
    fifty_two_week_high: float
    fifty_two_week_low: float
    currency: str
    short_name: str
    exchange: str
    source_url: str

def to_utc(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)


def is_market_open(meta, now=None):
    period = meta.get("currentTradingPeriod", {}).get("regular") or {}
    start, end = period.get("start"), period.get("end")

    if start is None or end is None:
        return False

    now = time.time() if now is None else now
    return start <= now <= end

REQUIRED_META = ("symbol", "regularMarketPrice", "regularMarketTime")


def parse_quote(meta, url, now=None):
    for key in REQUIRED_META:
        if meta.get(key) is None:
            raise YahooApiError(
                f"{url} returned meta without {key!r}; got keys {sorted(meta)}"
            )

    return Quote(
        symbol=meta["symbol"].upper(),
        quote_ts=to_utc(meta["regularMarketTime"]),
        price=meta["regularMarketPrice"],
        previous_close=meta.get("previousClose") or meta.get("chartPreviousClose"),
        day_high=meta.get("regularMarketDayHigh"),
        day_low=meta.get("regularMarketDayLow"),
        volume=meta.get("regularMarketVolume"),
        fifty_two_week_high=meta.get("fiftyTwoWeekHigh"),
        fifty_two_week_low=meta.get("fiftyTwoWeekLow"),
        currency=meta.get("currency"),
        short_name=meta.get("shortName"),
        exchange=meta.get("fullExchangeName"),
        source_url=url,
    )

def build_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


@dataclass(frozen=True)
class YahooClient:
    session: Any
    base_url: str
    timeout_seconds: float
    max_retries: int
    sleep: Callable = time.sleep

    def _get(self, path, params):
        """GET a JSON document, retrying only the failures worth retrying."""
        url = f"{self.base_url}/{path}?{urlencode(params)}"
        last_problem = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as error:
                last_problem = f"{type(error).__name__}: {error}"
            else:
                if response.status_code == 200:
                    try:
                        return response.json(), url
                    except ValueError as error:
                        raise YahooApiError(
                            f"{url} returned HTTP 200 but the body is not JSON: "
                            f"{response.text[:200]}"
                        ) from error

                if response.status_code not in RETRY_STATUS_CODES:
                    raise YahooApiError(
                        f"{url} returned HTTP {response.status_code}, "
                        f"which will not change on a retry: {response.text[:200]}"
                    )

                last_problem = f"HTTP {response.status_code}: {response.text[:200]}"

            if attempt < self.max_retries:
                self.sleep(BACKOFF_BASE_SECONDS * 2**attempt)

        raise YahooApiError(
            f"{url} failed {self.max_retries + 1} times. Last problem: {last_problem}"
        )

    def fetch_quote(self, symbol):
        payload, url = self._get(
            f"v8/finance/chart/{urlquote(symbol, safe='')}",
            {"range": CHART_RANGE, "interval": CHART_INTERVAL},
        )

        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise YahooApiError(f"{url} returned an error: {chart['error']}")

        results = chart.get("result") or []
        if not results:
            raise YahooApiError(f"{url} returned no result for {symbol!r}")

        return parse_quote(results[0].get("meta") or {}, url)