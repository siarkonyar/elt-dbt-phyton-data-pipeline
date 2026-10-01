"""The rules that turn a stream session or a rollup run into a status.

The page draws whatever these return as a coloured dot and a short label, so
the interesting part - which situation counts as healthy, which as a warning -
lives here where it can be tested without Streamlit.
"""

from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
STALE_AFTER = 90.0
CANDLE_GRACE = 300.0
HEALTHY_RUN = {"status": "ok", "error_message": None}


def ago(seconds):
    return NOW - timedelta(seconds=seconds)


def session(**overrides):
    """A healthy session during market hours; each test changes one thing."""
    row = {
        "status": "running",
        "error_message": None,
        "last_message_at": ago(2),
        "last_trade_at": ago(5),
        "market_open": True,
        "market_session": "regular",
    }
    return {**row, **overrides}


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "never"),
        (12, "12s ago"),
        (125, "2m ago"),
        (5400, "1.5h ago"),
    ],
)
def test_format_age_picks_the_largest_sensible_unit(
    dashboard_status, seconds, expected
):
    assert dashboard_status.format_age(seconds) == expected


def test_seconds_since_measures_from_now(dashboard_status):
    assert dashboard_status.seconds_since(ago(30), now=NOW) == 30


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_seconds_since_returns_none_for_a_missing_time(dashboard_status, missing):
    assert dashboard_status.seconds_since(missing, now=NOW) is None


def test_stream_status_without_a_session_says_not_started(dashboard_status):
    result = dashboard_status.stream_status(None, STALE_AFTER, now=NOW)

    assert result.level == "idle"
    assert result.label == "Not started"


def test_stream_status_is_live_when_the_market_is_open(dashboard_status):
    result = dashboard_status.stream_status(session(), STALE_AFTER, now=NOW)

    assert result.level == "ok"
    assert result.label == "Live"
    assert "market open" in result.detail


def test_stream_status_is_live_during_extended_hours(dashboard_status):
    row = session(market_open=False, market_session="post-market")

    result = dashboard_status.stream_status(row, STALE_AFTER, now=NOW)

    assert result.level == "ok"
    assert "post-market" in result.detail


def test_stream_status_is_calm_when_the_market_is_closed(dashboard_status):
    """Closed is normal, not a fault - so it must not look like one."""
    row = session(market_open=False, market_session=None, last_trade_at=ago(50_000))

    result = dashboard_status.stream_status(row, STALE_AFTER, now=NOW)

    assert result.level == "idle"
    assert result.label == "Market closed"


def test_stream_status_is_an_error_once_the_socket_goes_quiet(dashboard_status):
    row = session(last_message_at=ago(STALE_AFTER + 1))

    result = dashboard_status.stream_status(row, STALE_AFTER, now=NOW)

    assert result.level == "error"
    assert result.label == "Stream stale"


def test_stream_status_waits_when_nothing_has_arrived_yet(dashboard_status):
    row = session(last_message_at=None, last_trade_at=None)

    result = dashboard_status.stream_status(row, STALE_AFTER, now=NOW)

    assert result.level == "warn"
    assert result.label == "Connecting"


def test_stream_status_reports_a_failed_session_with_its_error(dashboard_status):
    row = session(status="failed", error_message="socket closed by peer")

    result = dashboard_status.stream_status(row, STALE_AFTER, now=NOW)

    assert result.level == "error"
    assert "socket closed by peer" in result.detail


def test_rollup_status_without_a_run_says_not_started(dashboard_status):
    result = dashboard_status.rollup_status(None, None, ago(5), CANDLE_GRACE, now=NOW)

    assert result.level == "idle"
    assert result.label == "Not started"


def test_rollup_status_is_ok_when_candles_keep_up(dashboard_status):
    result = dashboard_status.rollup_status(
        HEALTHY_RUN, ago(60), ago(5), CANDLE_GRACE, now=NOW
    )

    assert result.level == "ok"


def test_rollup_status_warns_when_trades_flow_but_candles_lag(dashboard_status):
    result = dashboard_status.rollup_status(
        HEALTHY_RUN, ago(CANDLE_GRACE + 60), ago(5), CANDLE_GRACE, now=NOW
    )

    assert result.level == "warn"
    assert result.label == "Behind"


def test_rollup_status_stays_ok_overnight_when_nothing_is_trading(
    dashboard_status,
):
    """Old candles and old trades together are a closed market, not a fault."""
    result = dashboard_status.rollup_status(
        HEALTHY_RUN, ago(50_000), ago(50_000), CANDLE_GRACE, now=NOW
    )

    assert result.level == "ok"


def test_rollup_status_reports_a_failed_run_with_its_error(dashboard_status):
    run = {"status": "failed", "error_message": "deadlock detected"}

    result = dashboard_status.rollup_status(run, ago(60), ago(5), CANDLE_GRACE, now=NOW)

    assert result.level == "error"
    assert "deadlock detected" in result.detail
