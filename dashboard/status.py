"""Turns a stream session or a rollup run into something a person can read.

No Streamlit in here. These functions only decide - is this healthy, a
warning, a fault, or simply quiet - and the pages decide how to draw it. That
split is what lets the rules be tested outside the dashboard image.
"""

from dataclasses import dataclass

import pandas as pd

# idle is its own level, not a kind of ok. A closed market is neither good
# news nor bad news, and painting it green would teach people to ignore green.
OK = "ok"
WARN = "warn"
ERROR = "error"
IDLE = "idle"

EXTENDED_SESSIONS = ("pre-market", "post-market")

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class Status:
    level: str
    label: str
    detail: str


def _is_missing(value):
    """None from psycopg2, NaN or NaT once pandas has had the column."""
    return value is None or pd.isna(value)


def _text(value):
    # A plain `if value:` is not enough here: NaN is truthy in Python.
    return None if _is_missing(value) or value == "" else str(value)


def seconds_since(value, now=None):
    if _is_missing(value):
        return None

    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    return (current - pd.Timestamp(value)).total_seconds()


def format_age(seconds):
    if seconds is None:
        return "never"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.0f}s ago"
    if seconds < SECONDS_PER_HOUR:
        return f"{seconds / SECONDS_PER_MINUTE:.0f}m ago"
    return f"{seconds / SECONDS_PER_HOUR:.1f}h ago"


def stream_status(session, stale_after_seconds, now=None):
    """Separates 'quiet market' from 'dead socket' - the point of the heartbeat."""
    if session is None:
        return Status(
            IDLE,
            "Not started",
            "No stream session recorded yet. Start the `stream` service.",
        )

    # Checked before anything else: a failed session's timestamps are simply
    # the last ones it saw, and could otherwise still read as live.
    if session["status"] == "failed":
        message = _text(session["error_message"])
        return Status(
            ERROR, "Stream failed", message or "The last session ended in an error."
        )

    message_age = seconds_since(session["last_message_at"], now)
    trade_age = seconds_since(session["last_trade_at"], now)

    if message_age is None:
        return Status(
            WARN, "Connecting", "Socket opened, but Finnhub has not sent anything yet."
        )

    if message_age > stale_after_seconds:
        return Status(
            ERROR,
            "Stream stale",
            f"Last message {format_age(message_age)}. "
            "Check the `stream` container logs.",
        )

    market = _text(session["market_session"])
    last_trade = f"last trade {format_age(trade_age)}"

    if not _is_missing(session["market_open"]) and bool(session["market_open"]):
        return Status(
            OK, "Live", f"US market open ({market or 'regular'}) · {last_trade}"
        )

    if market in EXTENDED_SESSIONS:
        return Status(OK, "Live", f"Regular session closed, {market} · {last_trade}")

    return Status(
        IDLE,
        "Market closed",
        f"Connected and healthy · {last_trade}. Prices resume at the open.",
    )


def rollup_status(run, newest_candle_at, last_trade_at, grace_seconds, now=None):
    if run is None:
        return Status(
            IDLE,
            "Not started",
            "No rollup run recorded yet. Start the `rollup` service.",
        )

    if run["status"] == "failed":
        message = _text(run["error_message"])
        return Status(
            ERROR, "Rollup failed", message or "The last run ended in an error."
        )

    candle_age = seconds_since(newest_candle_at, now)
    trade_age = seconds_since(last_trade_at, now)

    # Stale candles only mean a fault if trades are actually arriving.
    # Overnight there are no new trades AND no new candles, which is correct,
    # and an alarm that fires every night is one nobody reads.
    trades_flowing = trade_age is not None and trade_age < grace_seconds
    candles_behind = candle_age is None or candle_age > grace_seconds

    if trades_flowing and candles_behind:
        return Status(
            WARN,
            "Behind",
            f"Trades are arriving ({format_age(trade_age)}) but the newest "
            f"candle is {format_age(candle_age)}. Check the `rollup` container.",
        )

    return Status(OK, "Up to date", f"Newest candle {format_age(candle_age)}")
