import pytest


@pytest.mark.parametrize(
    "email",
    ["ada@example.com", "ada.lovelace+alerts@mail.example.co.uk", "a@b.io"],
)
def test_a_well_formed_address_is_an_email(api_emails, email):
    assert api_emails.is_email(email)


@pytest.mark.parametrize(
    "not_an_email",
    ["ada", "ada@", "@example.com", "ada@example", "a da@example.com", "a@@b.io", ""],
)
def test_anything_else_is_not_an_email(api_emails, not_an_email):
    assert not api_emails.is_email(not_an_email)


def test_an_address_longer_than_the_limit_is_not_an_email(api_emails):
    too_long = f"{'a' * api_emails.MAX_EMAIL_LENGTH}@example.com"

    assert not api_emails.is_email(too_long)
