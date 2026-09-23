import pytest

PASSWORD = "correct-horse-battery-staple"

# bcrypt is slow on purpose - that is what makes a stolen table expensive to
# crack. At the production cost factor of 12 a single hash takes ~250ms, and
# this file hashes about fifteen times. These tests only care that a password
# round-trips, never how long it took, so they buy the seconds back with the
# cheapest factor bcrypt accepts. Production never passes `rounds`.
TEST_ROUNDS = 4


def test_the_hash_is_not_the_password(api_passwords):
    hashed = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)

    assert hashed != PASSWORD


def test_the_right_password_verifies(api_passwords):
    hashed = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)

    assert api_passwords.verify_password(PASSWORD, hashed)


def test_a_wrong_password_does_not_verify(api_passwords):
    hashed = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)

    assert not api_passwords.verify_password("not-the-password", hashed)


def test_a_password_differing_only_in_case_does_not_verify(api_passwords):
    hashed = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)

    assert not api_passwords.verify_password(PASSWORD.upper(), hashed)


def test_two_hashes_of_the_same_password_are_different(api_passwords):
    """Each hash carries its own random salt. Without that, two users who
    picked the same password would have identical rows, and anyone who stole
    the table could see it."""
    first = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)
    second = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)

    assert first != second


def test_both_hashes_of_the_same_password_still_verify(api_passwords):
    """The other half of the salt story: differing hashes must not mean one of
    them stopped working."""
    first = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)
    second = api_passwords.hash_password(PASSWORD, rounds=TEST_ROUNDS)

    assert api_passwords.verify_password(PASSWORD, first)
    assert api_passwords.verify_password(PASSWORD, second)


def test_an_empty_password_is_rejected(api_passwords):
    with pytest.raises(ValueError):
        api_passwords.hash_password("", rounds=TEST_ROUNDS)


def test_a_password_longer_than_seventy_two_bytes_is_rejected(api_passwords):
    with pytest.raises(ValueError):
        api_passwords.hash_password("a" * 73, rounds=TEST_ROUNDS)


def test_a_password_of_exactly_seventy_two_bytes_is_accepted(api_passwords):
    longest_allowed = "a" * api_passwords.MAX_PASSWORD_BYTES

    hashed = api_passwords.hash_password(longest_allowed, rounds=TEST_ROUNDS)

    assert api_passwords.verify_password(longest_allowed, hashed)


def test_the_limit_is_measured_in_bytes_not_characters(api_passwords):
    """37 accented characters are only 37 characters but 74 bytes in UTF-8, so
    a length check written against `len(password)` would wave this through and
    bcrypt would raise deep inside the login route."""
    too_long = "é" * 37

    with pytest.raises(ValueError):
        api_passwords.hash_password(too_long, rounds=TEST_ROUNDS)


def test_a_corrupted_hash_does_not_verify(api_passwords):
    """A row whose password_hash got mangled must read as a wrong password.
    bcrypt raises ValueError on a salt it cannot parse, and an unguarded raise
    here would take the login route down for everyone, not just that user."""
    assert not api_passwords.verify_password(PASSWORD, "not-a-bcrypt-hash")
