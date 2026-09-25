"""parse_bearer, the pure half of api/auth.py.

Only the string parsing is tested here. get_current_user and require_admin are
FastAPI dependencies, and testing them in isolation would prove they work when
called the way this file calls them - not the way FastAPI does. They get real
coverage in Step 8, through requests that carry real tokens.

Pulling the parsing out into a plain function is what makes these eight cases
one line each instead of eight clients, tokens and config overrides.
"""
TOKEN = "abc123"


def test_a_bearer_header_yields_the_token(api_auth):
    assert api_auth.parse_bearer(f"Bearer {TOKEN}") == TOKEN


def test_the_scheme_is_matched_whatever_its_case(api_auth):
    """RFC 7235 says the scheme is case-insensitive, and real clients disagree
    about how to spell it. Rejecting "bearer" would break them for no reason."""
    assert api_auth.parse_bearer(f"bearer {TOKEN}") == TOKEN
    assert api_auth.parse_bearer(f"BEARER {TOKEN}") == TOKEN


def test_a_header_without_the_bearer_prefix_is_rejected(api_auth):
    """Basic auth sends base64 credentials, not a token. Decoding it as one
    would at best fail confusingly and at worst leak the header into a log."""
    assert api_auth.parse_bearer(f"Basic {TOKEN}") is None


def test_a_bare_token_with_no_scheme_is_rejected(api_auth):
    assert api_auth.parse_bearer(TOKEN) is None


def test_a_header_with_more_than_two_parts_is_rejected(api_auth):
    """Splitting on whitespace and taking [1] would quietly accept this and
    hand back a token that is not the whole token."""
    assert api_auth.parse_bearer(f"Bearer {TOKEN} extra") is None


def test_an_empty_header_is_rejected(api_auth):
    assert api_auth.parse_bearer("") is None


def test_a_missing_header_is_rejected(api_auth):
    """None is what FastAPI passes when the client sent no Authorization
    header at all, so it has to be an ordinary input here, not a crash."""
    assert api_auth.parse_bearer(None) is None


def test_a_bearer_prefix_with_no_token_is_rejected(api_auth):
    assert api_auth.parse_bearer("Bearer") is None
    assert api_auth.parse_bearer("Bearer ") is None
