from datetime import timedelta

from main import SocketEvents
from socket_client import TRADE


def test_a_fresh_events_object_has_seen_nothing():
    events = SocketEvents()

    assert events.last_message_at is None
    assert events.last_trade_at is None
    assert events.trades_seen == 0
    assert events.error is None
    assert not events.closed.is_set()


def test_recording_trades_adds_them_to_the_count():
    events = SocketEvents()

    events.record(TRADE, 3)

    assert events.trades_seen == 3


def test_trade_counts_accumulate_across_messages():
    events = SocketEvents()

    events.record(TRADE, 3)
    events.record(TRADE, 2)

    assert events.trades_seen == 5


def test_recording_a_trade_stamps_both_timestamps():
    events = SocketEvents()

    events.record(TRADE, 1)

    assert events.last_message_at is not None
    assert events.last_trade_at == events.last_message_at


def test_timestamps_are_timezone_aware_utc():
    events = SocketEvents()

    events.record(TRADE, 1)

    assert events.last_message_at.utcoffset() == timedelta(0)


def test_a_ping_updates_last_message_but_not_last_trade():
    events = SocketEvents()

    events.record("ping", None)

    assert events.last_message_at is not None
    assert events.last_trade_at is None


def test_a_trade_message_with_no_usable_trades_is_not_counted_as_a_trade():
    events = SocketEvents()

    events.record(TRADE, 0)

    assert events.trades_seen == 0
    assert events.last_trade_at is None
    assert events.last_message_at is not None


def test_a_failure_is_stored():
    events = SocketEvents()

    events.record("failed", "ConnectionResetError: boom")

    assert events.error == "ConnectionResetError: boom"


def test_a_close_sets_the_flag():
    events = SocketEvents()

    events.record("closed", 1006)

    assert events.closed.is_set()


def test_a_clean_close_is_not_recorded_as_a_failure():
    events = SocketEvents()

    events.record("closed", 1006)

    assert events.error is None