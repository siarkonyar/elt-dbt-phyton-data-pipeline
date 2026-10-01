from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

NUMERIC_FIELDS=("open", "high", "low", "close", "volume")

def test_numeric_prices_become_plain_floats(api_serialize, _candle_row):
    result = api_serialize.candle_to_dict(_candle_row())

    assert result["open"] == 100
    assert result["high"] == 108
    assert result["low"] == 95
    assert result["close"] == 104
    assert result["volume"] == 10

    for field in NUMERIC_FIELDS:
        assert isinstance(result[field], float)

def test_trade_count_is_an_int(api_serialize, _candle_row):
    trade_count=api_serialize.candle_to_dict(_candle_row())["trade_count"]
    assert isinstance(trade_count, int)
    assert trade_count == 4

def test_the_minute_becomes_an_iso_string(api_serialize, _candle_row):
    result = api_serialize.candle_to_dict(_candle_row())
    assert result["minute"] == "2024-01-01T12:00:00+00:00"

def test_the_symbol_is_passed_through_unchanged(api_serialize, _candle_row):
    symbol = api_serialize.candle_to_dict(_candle_row())["symbol"]

    assert symbol == "NVDA"
    assert isinstance(symbol, str)

def test_the_result_has_exactly_the_expected_keys(api_serialize, _candle_row):
    result = api_serialize.candle_to_dict(_candle_row())
    assert set(result.keys()) == {
        "symbol",
        "minute",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count"
    }


# --------------------------------------------------------------- alert_to_dict

CREATED = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
FIRED = datetime(2024, 1, 1, 12, 5, tzinfo=UTC)


def _alert_row(**overrides):
    """A waiting alert, the shape LIST_ALERTS_SQL returns."""
    defaults = {
        "alert_id": 7,
        "username": "ada",
        "symbol": "NVDA",
        "direction": "above",
        "threshold": Decimal("100.00"),
        "created_at": CREATED,
        "triggered_at": None,
        "triggered_price": None,
    }
    return SimpleNamespace(**{**defaults, **overrides})


def test_an_alert_threshold_becomes_a_plain_float(api_serialize):
    threshold = api_serialize.alert_to_dict(_alert_row())["threshold"]

    assert threshold == 100.0
    assert isinstance(threshold, float)


def test_an_alert_created_at_becomes_an_iso_string(api_serialize):
    result = api_serialize.alert_to_dict(_alert_row())

    assert result["created_at"] == "2024-01-01T12:00:00+00:00"


def test_a_waiting_alert_keeps_its_empty_trigger_fields(api_serialize):
    """NULL until the stream fires it. float(None) would crash the whole list."""
    result = api_serialize.alert_to_dict(_alert_row())

    assert result["triggered_at"] is None
    assert result["triggered_price"] is None


def test_a_fired_alert_carries_its_time_and_price(api_serialize):
    row = _alert_row(triggered_at=FIRED, triggered_price=Decimal("102.50"))

    result = api_serialize.alert_to_dict(row)

    assert result["triggered_at"] == "2024-01-01T12:05:00+00:00"
    assert result["triggered_price"] == 102.5
    assert isinstance(result["triggered_price"], float)


def test_an_alert_has_exactly_the_expected_keys(api_serialize):
    result = api_serialize.alert_to_dict(_alert_row())

    assert set(result.keys()) == {
        "alert_id",
        "username",
        "symbol",
        "direction",
        "threshold",
        "created_at",
        "triggered_at",
        "triggered_price",
    }
