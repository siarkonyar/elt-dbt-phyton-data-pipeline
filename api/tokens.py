import jwt

ALGORITHM = "HS256"

class TokenError(ValueError):
    """Token Error."""

def create_token(secret, email, role, now, expires_in_seconds):
    iat = int(now.timestamp())
    claims = {
        "sub": email,
        "role": role,
        "iat": iat,
        "exp": iat + expires_in_seconds,
    }

    return jwt.encode(claims, secret, ALGORITHM)

def decode_token(secret, token):
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "role"]},
        )
    except jwt.PyJWTError as error:
        raise TokenError("the token is not valid") from error
