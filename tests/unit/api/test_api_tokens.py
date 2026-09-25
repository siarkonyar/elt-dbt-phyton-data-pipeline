import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

# PyJWT is imported here and nowhere else in the tests, because half of this
# file's job is forging tokens the way an attacker would: signed with the
# wrong key, signed with the wrong algorithm, or not signed at all. api/tokens.py
# is the only production module allowed to know the library exists.

SECRET = "a-test-secret-that-is-long-enough-to-pass"
OTHER_SECRET = "a-different-secret-that-is-also-long-enough"
USERNAME = "ada"
ROLE = "user"
EXPIRES_IN = 3600


def _now():
    """Always timezone-aware. A naive datetime makes .timestamp() depend on the
    machine's local zone, so the same test would pass in London and fail in
    Istanbul."""
    return datetime.now(UTC)


def _claims():
    issued = int(_now().timestamp())
    return {"sub": USERNAME, "role": ROLE, "iat": issued, "exp": issued + EXPIRES_IN}


def _b64(part):
    """base64url with the padding stripped - how a JWT writes each segment."""
    return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()


def _unb64(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def test_the_token_carries_the_username(api_tokens):
    token = api_tokens.create_token(SECRET, USERNAME, ROLE, _now(), EXPIRES_IN)

    claims = api_tokens.decode_token(SECRET, token)

    assert claims["sub"] == USERNAME


def test_the_token_carries_the_role(api_tokens):
    token = api_tokens.create_token(SECRET, USERNAME, "admin", _now(), EXPIRES_IN)

    claims = api_tokens.decode_token(SECRET, token)

    assert claims["role"] == "admin"


def test_a_token_round_trips_through_the_same_secret(api_tokens):
    token = api_tokens.create_token(SECRET, USERNAME, ROLE, _now(), EXPIRES_IN)

    claims = api_tokens.decode_token(SECRET, token)

    assert claims["sub"] == USERNAME
    assert claims["role"] == ROLE


def test_a_token_signed_with_another_secret_is_rejected(api_tokens):
    """The signature is the only thing standing between a user and an admin
    token. Verify it against the wrong key and nothing else matters."""
    token = api_tokens.create_token(OTHER_SECRET, USERNAME, "admin", _now(), EXPIRES_IN)

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, token)


def test_an_expired_token_is_rejected(api_tokens):
    """Minted two hours ago with a one-hour life, so it went stale an hour
    before this line runs. No sleeping, no clock faking - `now` is an argument
    to create_token precisely so expiry can be tested this cheaply."""
    long_ago = _now() - timedelta(hours=2)
    token = api_tokens.create_token(SECRET, USERNAME, ROLE, long_ago, EXPIRES_IN)

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, token)


def test_a_token_that_expires_in_the_future_is_accepted(api_tokens):
    token = api_tokens.create_token(SECRET, USERNAME, ROLE, _now(), EXPIRES_IN)

    claims = api_tokens.decode_token(SECRET, token)

    assert claims["sub"] == USERNAME


def test_the_expiry_is_the_issue_time_plus_the_configured_lifetime(api_tokens):
    now = _now()

    token = api_tokens.create_token(SECRET, USERNAME, ROLE, now, EXPIRES_IN)

    claims = api_tokens.decode_token(SECRET, token)
    assert claims["iat"] == int(now.timestamp())
    assert claims["exp"] == claims["iat"] + EXPIRES_IN


def test_a_token_with_no_signature_is_rejected(api_tokens):
    """The alg:none attack, assembled by hand because PyJWT refuses to produce
    one. Strip the signature, claim the algorithm is "none", and hope the server
    believes the token's own header about how to verify it. Pinning
    algorithms=["HS256"] server-side is what refuses this."""
    header = {"alg": "none", "typ": "JWT"}
    unsigned = f"{_b64(header)}.{_b64(_claims())}."

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, unsigned)


def test_a_token_signed_with_a_different_algorithm_is_rejected(api_tokens):
    """Signed with the real secret, but HS512. The same pinned algorithm list
    refuses it, which is why the list matters more than the secret here."""
    forged = jwt.encode(_claims(), SECRET, algorithm="HS512")

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, forged)


def test_a_token_with_a_tampered_payload_is_rejected(api_tokens):
    """A JWT payload is base64, not encryption - anyone holding a token can
    read it and edit it. Promote the role to admin, keep the original
    signature, and the signature no longer matches the payload."""
    token = api_tokens.create_token(SECRET, USERNAME, ROLE, _now(), EXPIRES_IN)
    header, payload, signature = token.split(".")
    promoted = {**_unb64(payload), "role": "admin"}

    forged = f"{header}.{_b64(promoted)}.{signature}"

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, forged)


def test_a_token_missing_the_role_claim_is_rejected(api_tokens):
    """Properly signed, just incomplete. Rejecting it in the library beats a
    KeyError three functions later, inside a route."""
    issued = int(_now().timestamp())
    without_role = {"sub": USERNAME, "iat": issued, "exp": issued + EXPIRES_IN}
    forged = jwt.encode(without_role, SECRET, algorithm="HS256")

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, forged)


def test_a_token_missing_the_expiry_claim_is_rejected(api_tokens):
    """A token with no exp never expires. PyJWT does not mind that by default,
    so decode_token has to ask for the claim explicitly."""
    without_expiry = {"sub": USERNAME, "role": ROLE, "iat": int(_now().timestamp())}
    forged = jwt.encode(without_expiry, SECRET, algorithm="HS256")

    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, forged)


def test_an_empty_token_is_rejected(api_tokens):
    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, "")


def test_garbage_that_is_not_a_token_is_rejected(api_tokens):
    with pytest.raises(api_tokens.TokenError):
        api_tokens.decode_token(SECRET, "this-is-not-a-token-at-all")
