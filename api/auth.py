from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from config import load_config
from tokens import TokenError, decode_token

BEARER_SCHEME = "bearer"
ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class AuthenticatedUser: # could have been dict
    username: str
    role: str


def parse_bearer(header):
    if not header:
        return None

    parts = header.split()

    if len(parts) != 2:
        return None
    #Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZGEifQ.xK3p -- we split because the auth comes like this

    scheme, token = parts

    if scheme.lower() != BEARER_SCHEME:
        return None

    return token or None


@lru_cache(maxsize=1)
def get_config():
    return load_config()


def _unauthenticated():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    authorization: str | None = Header(default=None),
    config=Depends(get_config),
):
    token = parse_bearer(authorization)

    if token is None:
        raise _unauthenticated()

    try:
        claims = decode_token(config.jwt_secret, token)
    except TokenError as error:
        raise _unauthenticated() from error

    # decode_token requires sub and role, so neither lookup can KeyError here.
    return AuthenticatedUser(username=claims["sub"], role=claims["role"])


def require_admin(user=Depends(get_current_user)):
    if user.role != ADMIN_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this action needs an admin account",
        )

    return user
