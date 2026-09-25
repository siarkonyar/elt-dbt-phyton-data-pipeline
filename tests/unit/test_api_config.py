import dataclasses

import pytest

# Long enough to clear MIN_SECRET_LENGTH. A shorter one would raise before
# load_config ever reached the setting under test, so the test would pass
# for the wrong reason.
SECRET = "a-test-secret-that-is-long-enough-to-pass"


def test_a_missing_jwt_secret_is_rejected(api_config):
    with pytest.raises(api_config.ConfigError):
        api_config.load_config({})


def test_the_defaults_are_used_when_only_a_secret_is_given(api_config):
    config = api_config.load_config({"JWT_SECRET": SECRET})

    assert config.token_expiry_seconds == 3600
    assert config.admin_username is None
    assert config.admin_password is None


def test_values_are_read_from_the_environment(api_config):
    config = api_config.load_config(
        {
            "JWT_SECRET": SECRET,
            "JWT_EXPIRY_SECONDS": "900",
            "API_ADMIN_USERNAME": "ada",
            "API_ADMIN_PASSWORD": "a-password",
        }
    )

    assert config.jwt_secret == SECRET
    assert config.token_expiry_seconds == 900
    assert config.admin_username == "ada"
    assert config.admin_password == "a-password"


def test_a_blank_jwt_secret_is_rejected(api_config):
    """Whitespace, not "". An empty string is already falsy, so it takes the
    same branch as a missing one. Spaces are the case a naive `if not raw`
    would let straight through."""
    with pytest.raises(api_config.ConfigError):
        api_config.load_config({"JWT_SECRET": "   "})


def test_a_secret_shorter_than_thirty_two_characters_is_rejected(api_config):
    with pytest.raises(api_config.ConfigError):
        api_config.load_config({"JWT_SECRET": "too-short"})


def test_a_secret_of_exactly_thirty_two_characters_is_accepted(api_config):
    shortest_allowed = "a" * api_config.MIN_SECRET_LENGTH

    config = api_config.load_config({"JWT_SECRET": shortest_allowed})

    assert config.jwt_secret == shortest_allowed


def test_the_error_for_a_short_secret_does_not_contain_the_secret(api_config):
    """A ConfigError ends up in container logs and CI job summaries. Every
    other setting in this repo reports `got {raw!r}`; this one must not."""
    secret = "short-but-memorable"

    with pytest.raises(api_config.ConfigError) as caught:
        api_config.load_config({"JWT_SECRET": secret})

    assert secret not in str(caught.value)


def test_an_unparseable_expiry_is_rejected(api_config):
    with pytest.raises(api_config.ConfigError):
        api_config.load_config(
            {"JWT_SECRET": SECRET, "JWT_EXPIRY_SECONDS": "not-a-number"}
        )


def test_a_zero_expiry_is_rejected(api_config):
    with pytest.raises(api_config.ConfigError):
        api_config.load_config({"JWT_SECRET": SECRET, "JWT_EXPIRY_SECONDS": "0"})


def test_an_expiry_longer_than_a_day_is_rejected(api_config):
    with pytest.raises(api_config.ConfigError):
        api_config.load_config({"JWT_SECRET": SECRET, "JWT_EXPIRY_SECONDS": "86401"})


def test_an_expiry_of_exactly_a_day_is_accepted(api_config):
    longest_allowed = str(api_config.MAX_EXPIRY_SECONDS)

    config = api_config.load_config(
        {"JWT_SECRET": SECRET, "JWT_EXPIRY_SECONDS": longest_allowed}
    )

    assert config.token_expiry_seconds == api_config.MAX_EXPIRY_SECONDS


def test_an_admin_username_without_a_password_is_rejected(api_config):
    with pytest.raises(api_config.ConfigError):
        api_config.load_config({"JWT_SECRET": SECRET, "API_ADMIN_USERNAME": "ada"})


def test_an_admin_password_without_a_username_is_rejected(api_config):
    """The dangerous direction: a password with nobody to belong to must not
    quietly seed an account under some default name."""
    with pytest.raises(api_config.ConfigError):
        api_config.load_config(
            {"JWT_SECRET": SECRET, "API_ADMIN_PASSWORD": "a-password"}
        )


def test_the_config_cannot_be_mutated_after_it_is_built(api_config):
    config = api_config.load_config({"JWT_SECRET": SECRET})

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.jwt_secret = "something-else-entirely"
