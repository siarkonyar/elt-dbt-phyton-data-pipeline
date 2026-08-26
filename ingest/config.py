import os
from dataclasses import dataclass

DEFAULTS = {
    "STOCK_SYMBOLS": "AMZN,NVDA,GOOGL,TSLA,NFLX",
    "YAHOO_BASE_URL": "https://query1.finance.yahoo.com",
    "YAHOO_TIMEOUT_SECONDS": "10",
    "YAHOO_MAX_RETRIES": "4",
}


class ConfigError(RuntimeError):
    """Raised when a setting is missing, unparseable, or out of range."""


def parse_symbols(raw):
    """"amzn, NVDA,, NVDA " -> ("AMZN", "NVDA")"""
    cleaned = [piece.strip().upper() for piece in raw.split(",")]
    symbols = tuple(dict.fromkeys(piece for piece in cleaned if piece))

    if not symbols:
        raise ConfigError(f"STOCK_SYMBOLS has no usable symbols in it: {raw!r}")

    return symbols

@dataclass(frozen=True)
class IngestConfig:
    symbols: tuple
    base_url: str
    timeout_seconds: float
    max_retries: int

def _read_number(env, name, parse):
    raw = env.get(name, DEFAULTS[name])
    try:
        return parse(raw)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error

def load_config(env=None):
    env = os.environ if env is None else env

    timeout_seconds = _read_number(env, "YAHOO_TIMEOUT_SECONDS", float)
    max_retries = _read_number(env, "YAHOO_MAX_RETRIES", int)

    if timeout_seconds <= 0:
        raise ConfigError(f"YAHOO_TIMEOUT_SECONDS must be positive, got {timeout_seconds}")

    if max_retries < 0:
        raise ConfigError(f"YAHOO_MAX_RETRIES cannot be negative, got {max_retries}")

    return IngestConfig(
        symbols=parse_symbols(env.get("STOCK_SYMBOLS", DEFAULTS["STOCK_SYMBOLS"])),
        base_url=env.get("YAHOO_BASE_URL", DEFAULTS["YAHOO_BASE_URL"]).rstrip("/"),
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )