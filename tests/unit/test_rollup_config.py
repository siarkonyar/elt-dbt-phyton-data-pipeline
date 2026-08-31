from dataclasses import FrozenInstanceError

import pytest


def test_defaults_are_applied_when_nothing_is_set(rollup_config):
    config = rollup_config.load_config({})

    assert config.interval_seconds == 60.0
    assert config.window_minutes == 10
    assert config.max_rows == 200000


def test_values_are_read_from_the_environment(rollup_config):
    config = rollup_config.load_config({
        "ROLLUP_INTERVAL_SECONDS": "30",
        "ROLLUP_WINDOW_MINUTES": "5",
        "ROLLUP_MAX_ROWS": "1000",
    })

    assert config.interval_seconds == 30.0
    assert config.window_minutes == 5
    assert config.max_rows == 1000


def test_an_unparseable_number_is_rejected(rollup_config):
    with pytest.raises(rollup_config.ConfigError):
        rollup_config.load_config({"ROLLUP_INTERVAL_SECONDS": "soon"})


def test_a_zero_interval_is_rejected(rollup_config):
    with pytest.raises(rollup_config.ConfigError):
        rollup_config.load_config({"ROLLUP_INTERVAL_SECONDS": "0"})


def test_a_window_shorter_than_one_minute_is_rejected(rollup_config):
    with pytest.raises(rollup_config.ConfigError):
        rollup_config.load_config({"ROLLUP_WINDOW_MINUTES": "0"})


def test_a_max_rows_below_one_is_rejected(rollup_config):
    with pytest.raises(rollup_config.ConfigError):
        rollup_config.load_config({"ROLLUP_MAX_ROWS": "0"})


def test_a_window_that_cannot_cover_the_interval_is_rejected(rollup_config):
    # A 15-minute interval with a 10-minute window loses 5 minutes of
    # history out of every 15, forever, without any error.
    with pytest.raises(rollup_config.ConfigError):
        rollup_config.load_config({
            "ROLLUP_INTERVAL_SECONDS": "900",
            "ROLLUP_WINDOW_MINUTES": "10",
        })


def test_a_window_exactly_covering_the_interval_is_allowed(rollup_config):
    config = rollup_config.load_config({
        "ROLLUP_INTERVAL_SECONDS": "600",
        "ROLLUP_WINDOW_MINUTES": "10",
    })

    assert config.interval_seconds == 600.0


def test_the_config_cannot_be_changed_after_it_is_built(rollup_config):
    config = rollup_config.load_config({})

    with pytest.raises(FrozenInstanceError):
        config.interval_seconds = 5