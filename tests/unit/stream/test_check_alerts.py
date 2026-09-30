from datetime import UTC, datetime

from sqlalchemy.exc import ProgrammingError

from main import check_alerts
from socket_client import Trade

A_TRADE = Trade(
    symbol="NVDA",
    trade_ts=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    price=102.0,
    volume=1.0,
    conditions="",
)


class EngineThatMustNotBeUsed:
    def begin(self):
        raise AssertionError("an empty batch opened a transaction")


class EngineWithNoAlertsTable:
    """What the stream meets if it starts before the api has created
    price_alerts."""

    def begin(self):
        raise ProgrammingError(
            "SELECT", {}, Exception('relation "price_alerts" does not exist')
        )


def test_an_empty_batch_does_not_touch_the_database():
    """Most flushes carry no trades while the market is closed. Reading the
    alerts table once a second for nothing would be pure waste."""
    assert check_alerts(EngineThatMustNotBeUsed(), ()) == 0


def test_a_database_failure_is_logged_and_never_raised(capsys):
    """The trades are already saved by the time this runs. A broken alert
    check must not take the stream down with it."""
    assert check_alerts(EngineWithNoAlertsTable(), (A_TRADE,)) == 0

    assert "alert check failed" in capsys.readouterr().err
