import os
from dataclasses import dataclass

DEFAULTS = {
    "JWT_EXPIRY_SECONDS": "3600",
}

# HS256 signatures are only as strong as the key behind them, and a short key
# is a guessable key. 32 is what `openssl rand -hex 32` produces.
MIN_SECRET_LENGTH = 32

# A stateless token cannot be revoked, so its lifetime is also the longest a
# demoted admin keeps the old powers. A day is already generous.
MAX_EXPIRY_SECONDS = 86400


class ConfigError(RuntimeError):
    """Raised when a setting is missing, unparseable, or out of range."""


@dataclass(frozen=True)
class ApiConfig:
    jwt_secret: str
    token_expiry_seconds: int
    admin_username: str | None
    admin_password: str | None


def _read_number(env, name, parse):
    raw = env.get(name) or DEFAULTS[name]
    try:
        return parse(raw)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error


def _read_secret(env):
    # Stripped, because a trailing newline in .env would otherwise become part
    # of the signing key, and every token would break the next time someone
    # retyped the file.
    raw = (env.get("JWT_SECRET") or "").strip()

    if not raw:
        raise ConfigError(
            "JWT_SECRET is not set. Generate one with `openssl rand -hex 32` "
            "and put it in .env."
        )

    # Reports the length, never the value. Every other setting in this repo
    # ends its error with `got {raw!r}`, but this one reaches container logs
    # and CI job summaries, and the secret is the whole of the security.
    if len(raw) < MIN_SECRET_LENGTH:
        raise ConfigError(
            f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters, "
            f"got {len(raw)}."
        )

    return raw


def _read_admin(env):
    """Both or neither.

    A password with no username would otherwise seed an account under some
    invented default name, which is how installations end up with credentials
    nobody chose. Unset is a valid answer: it means seed no admin at all.
    """
    # The password is not stripped - spaces can be part of one.
    username = (env.get("API_ADMIN_USERNAME") or "").strip() or None
    password = env.get("API_ADMIN_PASSWORD") or None

    if username and not password:
        raise ConfigError(
            "API_ADMIN_USERNAME is set but API_ADMIN_PASSWORD is not. Set both "
            "to seed an admin, or neither to seed none."
        )

    if password and not username:
        raise ConfigError(
            "API_ADMIN_PASSWORD is set but API_ADMIN_USERNAME is not. Set both "
            "to seed an admin, or neither to seed none."
        )

    return username, password


def load_config(env=None):
    env = os.environ if env is None else env

    secret = _read_secret(env)
    expiry = _read_number(env, "JWT_EXPIRY_SECONDS", int)

    if expiry < 1:
        raise ConfigError(f"JWT_EXPIRY_SECONDS must be at least 1, got {expiry}")

    if expiry > MAX_EXPIRY_SECONDS:
        raise ConfigError(
            f"JWT_EXPIRY_SECONDS must be at most {MAX_EXPIRY_SECONDS}, got "
            f"{expiry}. A token nobody can revoke should not outlive a day."
        )

    admin_username, admin_password = _read_admin(env)

    return ApiConfig(
        jwt_secret=secret,
        token_expiry_seconds=expiry,
        admin_username=admin_username,
        admin_password=admin_password,
    )
