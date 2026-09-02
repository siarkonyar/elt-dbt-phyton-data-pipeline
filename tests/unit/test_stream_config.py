from dataclasses import FrozenInstanceError

import pytest
from config import ConfigError, load_config, parse_symbols


def env(**overrides):
    """The smallest environment that loads, plus whatever a test changes.

    Only the API key has no default, so every other setting can be left out.
    """
    return {"FINNHUB_API_KEY": "test-key", **overrides}


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

def test_defaults_are_applied_when_only_the_key_is_set():
    config = load_config(env())

    assert config.timeout_seconds == 10.0
    assert config.flush_interval_seconds == 1.0
    assert config.flush_max_rows == 500
    assert config.reconnect_min_seconds == 1.0
    assert config.reconnect_max_seconds == 60.0
    assert config.market_status_interval_seconds == 60.0
    assert config.stale_after_seconds == 90.0


def test_the_default_symbols_are_used_when_none_are_given():
    config = load_config(env())

    assert config.symbols == ("AMZN", "NVDA", "GOOGL", "TSLA", "NFLX")


def test_values_are_read_from_the_environment():
    config = load_config(env(
        FINNHUB_TIMEOUT_SECONDS="5",
        FLUSH_INTERVAL_SECONDS="2",
        FLUSH_MAX_ROWS="1000",
        RECONNECT_MIN_SECONDS="3",
        RECONNECT_MAX_SECONDS="30",
        MARKET_STATUS_INTERVAL_SECONDS="15",
        STALE_AFTER_SECONDS="45",
    ))

    assert config.timeout_seconds == 5.0
    assert config.flush_interval_seconds == 2.0
    assert config.flush_max_rows == 1000
    assert config.reconnect_min_seconds == 3.0
    assert config.reconnect_max_seconds == 30.0
    assert config.market_status_interval_seconds == 15.0
    assert config.stale_after_seconds == 45.0


# --- the API key, the one setting with no default ---

def test_a_missing_api_key_is_rejected():
    with pytest.raises(ConfigError):
        load_config({})


def test_an_api_key_of_only_spaces_is_rejected():
    # An empty line in .env leaves the variable set but blank, which would
    # otherwise sail through and fail much later as a socket rejection.
    with pytest.raises(ConfigError):
        load_config({"FINNHUB_API_KEY": "   "})


def test_surrounding_whitespace_is_trimmed_off_the_key():
    config = load_config({"FINNHUB_API_KEY": "  test-key  "})

    assert config.api_key == "test-key"


def test_the_socket_endpoint_carries_the_key_in_the_query_string():
    config = load_config(env(FINNHUB_WS_URL="wss://example.test"))

    assert config.ws_endpoint == "wss://example.test?token=test-key"


# --- URLs ---

def test_a_trailing_slash_is_stripped_from_the_socket_url():
    # Without this the endpoint becomes "wss://example.test/?token=..."
    config = load_config(env(FINNHUB_WS_URL="wss://example.test/"))

    assert config.ws_url == "wss://example.test"


def test_a_trailing_slash_is_stripped_from_the_base_url():
    # The caller appends "/stock/market-status", so a kept slash would send
    # the request to a doubled path.
    config = load_config(env(FINNHUB_BASE_URL="https://example.test/api/v1/"))

    assert config.base_url == "https://example.test/api/v1"


# --- symbols ---

def test_symbols_are_read_from_the_environment():
    config = load_config(env(STOCK_SYMBOLS="tsla, amzn"))

    assert config.symbols == ("TSLA", "AMZN")


def test_a_blank_symbol_list_falls_back_to_the_defaults():
    config = load_config(env(STOCK_SYMBOLS=""))

    assert config.symbols == ("AMZN", "NVDA", "GOOGL", "TSLA", "NFLX")


def test_a_symbol_list_with_nothing_usable_in_it_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(STOCK_SYMBOLS=" , , "))


# --- numbers that cannot be parsed ---

def test_an_unparseable_number_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(FLUSH_INTERVAL_SECONDS="soon"))


def test_a_fractional_row_limit_is_rejected():
    # int("500.5") raises, so a plausible-looking value fails fast rather
    # than silently truncating.
    with pytest.raises(ConfigError):
        load_config(env(FLUSH_MAX_ROWS="500.5"))


# --- numbers that parse but make no sense ---

def test_a_zero_timeout_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(FINNHUB_TIMEOUT_SECONDS="0"))


def test_a_zero_flush_interval_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(FLUSH_INTERVAL_SECONDS="0"))


def test_a_row_limit_below_one_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(FLUSH_MAX_ROWS="0"))


def test_a_zero_reconnect_floor_is_rejected():
    # A zero floor turns the backoff into a busy loop against Finnhub.
    with pytest.raises(ConfigError):
        load_config(env(RECONNECT_MIN_SECONDS="0"))


def test_a_reconnect_ceiling_below_the_floor_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(RECONNECT_MIN_SECONDS="30", RECONNECT_MAX_SECONDS="10"))


def test_a_reconnect_ceiling_equal_to_the_floor_is_allowed():
    # A fixed delay is a legitimate choice, just not a shrinking one.
    config = load_config(env(RECONNECT_MIN_SECONDS="5", RECONNECT_MAX_SECONDS="5"))

    assert config.reconnect_max_seconds == 5.0


def test_a_zero_market_status_interval_is_rejected():
    with pytest.raises(ConfigError):
        load_config(env(MARKET_STATUS_INTERVAL_SECONDS="0"))


def test_a_stale_timeout_at_the_flush_interval_is_rejected():
    # The stream would call itself stale in the same breath as a healthy
    # flush, so the two must not be equal.
    with pytest.raises(ConfigError):
        load_config(env(FLUSH_INTERVAL_SECONDS="10", STALE_AFTER_SECONDS="10"))


def test_a_stale_timeout_above_the_flush_interval_is_allowed():
    config = load_config(env(FLUSH_INTERVAL_SECONDS="10", STALE_AFTER_SECONDS="11"))

    assert config.stale_after_seconds == 11.0


# --- immutability ---

def test_the_config_cannot_be_changed_after_it_is_built():
    config = load_config(env())

    with pytest.raises(FrozenInstanceError):
        config.flush_max_rows = 5
