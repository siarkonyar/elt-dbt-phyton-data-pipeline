import json
from datetime import datetime, timezone

from socket_client import ERROR, TRADE, parse_message


def test_parses_a_trade_message_into_one_trade():
    # Arrange
    raw = json.dumps({
        "type": "trade",
        "data": [
            {"s": "NVDA", "t": 1700000000000, "p": 123.45, "v": 10, "c": ["1", "12"]}
        ],
    })

    # Act
    message_type, trades = parse_message(raw)

    # Assert
    assert message_type == TRADE
    assert len(trades) == 1
    assert trades[0].symbol == "NVDA"
    assert trades[0].price == 123.45
    assert trades[0].volume == 10.0
    assert trades[0].conditions == "1,12"


def test_converts_millisecond_epoch_to_utc():
    raw = json.dumps({
        "type": "trade",
        "data": [{"s": "NVDA", "t": 1700000000000, "p": 1.0}],
    })

    _, trades = parse_message(raw)

    assert trades[0].trade_ts == datetime(
        2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc
    )


def test_ping_message_yields_no_trades():
    message_type, trades = parse_message(json.dumps({"type": "ping"}))

    assert message_type == "ping"
    assert trades == ()


def test_malformed_json_returns_error_instead_of_raising():
    message_type, trades = parse_message("not json at all")

    assert message_type == ERROR
    assert trades == ()


def test_missing_volume_and_conditions_fall_back_to_defaults():
    raw = json.dumps({
        "type": "trade",
        "data": [{"s": "NVDA", "t": 1700000000000, "p": 1.0}],
    })

    _, trades = parse_message(raw)

    assert trades[0].volume == 0.0
    assert trades[0].conditions == ""


def test_trade_with_a_missing_field_is_skipped_not_raised():
    raw = json.dumps({
        "type": "trade",
        "data": [
            {"t": 1700000000000, "p": 1.0},                  # no "s"
            {"s": "NVDA", "t": 1700000000000, "p": 2.0},     # fine
        ],
    })

    message_type, trades = parse_message(raw)

    assert message_type == TRADE
    assert len(trades) == 1
    assert trades[0].price == 2.0


def test_json_that_is_not_an_object_returns_error():
    message_type, trades = parse_message("[1, 2, 3]")

    assert message_type == ERROR
    assert trades == ()