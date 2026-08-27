import os
from dataclasses import dataclass

DEFAULTS = {
    "STOCK_SYMBOLS": "AMZN,NVDA,GOOGL,TSLA,NFLX",
    "FINNHUB_BASE_URL": "https://finnhub.io/api/v1",
    "FINNHUB_TIMEOUT_SECONDS": "10",
    "FINNHUB_MAX_RETRIES": "4",
    "FINNHUB_RATE_PER_MINUTE": "60",
    "FINNHUB_RATE_BURST": "10",
    "BREAKER_FAILURE_THRESHOLD": "5",
    "BREAKER_COOLDOWN_SECONDS": "60",
    "POLL_INTERVAL_SECONDS": "15",
    "MARKET_CLOSED_POLL_SECONDS": "300",
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
    api_key: str
    symbols: tuple
    base_url: str
    timeout_seconds: float
    max_retries: int
    rate_per_minute: float
    rate_burst: int
    breaker_failure_threshold: int
    breaker_cooldown_seconds: float
    poll_interval_seconds: float
    market_closed_poll_seconds: float

    @property
    def rate_per_second(self):
        return self.rate_per_minute / 60.0

def _read_required(env, name, hint):
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. {hint}")
    return value

def _read_number(env, name, parse):
    raw = env.get(name, DEFAULTS[name])
    try:
        return parse(raw)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error

def load_config(env=None):
    env = os.environ if env is None else env

    timeout_seconds = _read_number(env, "FINNHUB_TIMEOUT_SECONDS", float)
    max_retries = _read_number(env, "FINNHUB_MAX_RETRIES", int)
    rate_per_minute = _read_number(env, "FINNHUB_RATE_PER_MINUTE", float)
    rate_burst = _read_number(env, "FINNHUB_RATE_BURST", int)
    failure_threshold = _read_number(env, "BREAKER_FAILURE_THRESHOLD", int)
    cooldown_seconds = _read_number(env, "BREAKER_COOLDOWN_SECONDS", float)
    poll_interval = _read_number(env, "POLL_INTERVAL_SECONDS", float)
    closed_poll_interval = _read_number(env, "MARKET_CLOSED_POLL_SECONDS", float)

    if timeout_seconds <= 0:
        raise ConfigError(f"FINNHUB_TIMEOUT_SECONDS must be positive, got {timeout_seconds}")
    if max_retries < 0:
        raise ConfigError(f"FINNHUB_MAX_RETRIES cannot be negative, got {max_retries}")
    if rate_per_minute <= 0:
        raise ConfigError(f"FINNHUB_RATE_PER_MINUTE must be positive, got {rate_per_minute}")
    if rate_burst < 1:
        raise ConfigError(f"FINNHUB_RATE_BURST must be at least 1, got {rate_burst}")
    if poll_interval <= 0:
        raise ConfigError(f"POLL_INTERVAL_SECONDS must be positive, got {poll_interval}")
    if closed_poll_interval <= 0:
        raise ConfigError(
            f"MARKET_CLOSED_POLL_SECONDS must be positive, got {closed_poll_interval}"
        )

    return IngestConfig(
        api_key=_read_required(
            env, "FINNHUB_API_KEY", "Get a free key at finnhub.io and put it in .env"
        ),
        symbols=parse_symbols(env.get("STOCK_SYMBOLS", DEFAULTS["STOCK_SYMBOLS"])),
        base_url=env.get("FINNHUB_BASE_URL", DEFAULTS["FINNHUB_BASE_URL"]).rstrip("/"),
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        rate_per_minute=rate_per_minute,
        rate_burst=rate_burst,
        breaker_failure_threshold=failure_threshold,
        breaker_cooldown_seconds=cooldown_seconds,
        poll_interval_seconds=poll_interval,
        market_closed_poll_seconds=closed_poll_interval,
    )