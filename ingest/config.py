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