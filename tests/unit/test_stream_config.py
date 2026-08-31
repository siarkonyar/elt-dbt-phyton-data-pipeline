import pytest
from config import ConfigError, parse_symbols


def test_uppercases_lowercase_symbols():
    # Arrange
    raw = "amzn,nvda"

    # Act
    symbols = parse_symbols(raw)

    # Assert
    assert symbols == ("AMZN", "NVDA")


def test_strips_whitespace_around_symbols():
    assert parse_symbols(" AMZN , NVDA ") == ("AMZN", "NVDA")


def test_skips_empty_entries_left_by_double_commas():
    assert parse_symbols("AMZN,,NVDA") == ("AMZN", "NVDA")


def test_drops_duplicates_and_keeps_first_seen_order():
    assert parse_symbols("NVDA,AMZN,NVDA") == ("NVDA", "AMZN")


def test_raises_when_nothing_usable_is_left():
    with pytest.raises(ConfigError):
        parse_symbols(" , , ")