from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace


def _candle_row(**overrides):
  defaults = {
      "symbol": "NVDA",
      "minute": datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
      "open": Decimal("100.0"),
      "high": Decimal("108.0"),
      "low": Decimal("95.0"),
      "close": Decimal("104.0"),
      "volume": Decimal("10.0"),
      "trade_count": 4,
  }
  return SimpleNamespace(**{**defaults, **overrides})

NUMERIC_FIELDS=("open", "high", "low", "close", "volume")

def test_numeric_prices_become_plain_floats(api_serialize):
    result = api_serialize.candle_to_dict(_candle_row())

    assert result["open"] == 100
    assert result["high"] == 108
    assert result["low"] == 95
    assert result["close"] == 104
    assert result["volume"] == 10

    for field in NUMERIC_FIELDS:
        assert isinstance(result[field], float)

def test_trade_count_is_an_int(api_serialize):
    trade_count=api_serialize.candle_to_dict(_candle_row())["trade_count"]
    assert isinstance(trade_count, int)
    assert trade_count == 4

def test_the_minute_becomes_an_iso_string(api_serialize):
    result = api_serialize.candle_to_dict(_candle_row())
    assert result["minute"] == "2024-01-01T12:00:00+00:00"

def test_the_symbol_is_passed_through_unchanged(api_serialize):
    symbol = api_serialize.candle_to_dict(_candle_row())["symbol"]

    assert symbol == "NVDA"
    assert isinstance(symbol, str)

def test_the_result_has_exactly_the_expected_keys(api_serialize):
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
