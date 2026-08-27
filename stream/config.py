import os
from dataclasses import dataclass

DEFAULTS = {
    "STOCK_SYMBOLS": "AMZN,NVDA,GOOGL,TSLA,NFLX",
    "FINNHUB_WS_URL": "wss://ws.finnhub.io",
    "FINNHUB_BASE_URL": "https://finnhub.io/api/v1",
    "FINNHUB_TIMEOUT_SECONDS": "10",
    "FLUSH_INTERVAL_SECONDS": "1",
    "FLUSH_MAX_ROWS": "500",
    "RECONNECT_MIN_SECONDS": "1",
    "RECONNECT_MAX_SECONDS": "60",
    "MARKET_STATUS_INTERVAL_SECONDS": "60",
    "STALE_AFTER_SECONDS": "90",
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
class StreamConfig:
    api_key: str
    symbols: tuple
    ws_url: str
    base_url: str
    timeout_seconds: float
    flush_interval_seconds: float
    flush_max_rows: int
    reconnect_min_seconds: float
    reconnect_max_seconds: float
    market_status_interval_seconds: float
    stale_after_seconds: float

    @property
    def ws_endpoint(self):
        """Finnhub authenticates the socket with the key in the query string."""
        return f"{self.ws_url}?token={self.api_key}"

#these both are for .env
def _read_required(env, name, hint):
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. {hint}")
    return value


def _read_number(env, name, parse):
    raw = env.get(name) or DEFAULTS[name]
    try:
        return parse(raw)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error

def load_config(env=None):
    env = os.environ if env is None else env

    timeout_seconds = _read_number(env, "FINNHUB_TIMEOUT_SECONDS", float)
    flush_interval = _read_number(env, "FLUSH_INTERVAL_SECONDS", float)
    flush_max_rows = _read_number(env, "FLUSH_MAX_ROWS", int)
    reconnect_min = _read_number(env, "RECONNECT_MIN_SECONDS", float)
    reconnect_max = _read_number(env, "RECONNECT_MAX_SECONDS", float)
    status_interval = _read_number(env, "MARKET_STATUS_INTERVAL_SECONDS", float)
    stale_after = _read_number(env, "STALE_AFTER_SECONDS", float)

    if timeout_seconds <= 0:
        raise ConfigError(
            f"FINNHUB_TIMEOUT_SECONDS must be positive, got {timeout_seconds}"
        )
    if flush_interval <= 0:
        raise ConfigError(
            f"FLUSH_INTERVAL_SECONDS must be positive, got {flush_interval}"
        )
    if flush_max_rows < 1:
        raise ConfigError(f"FLUSH_MAX_ROWS must be at least 1, got {flush_max_rows}")
    if reconnect_min <= 0:
        raise ConfigError(
            f"RECONNECT_MIN_SECONDS must be positive, got {reconnect_min}"
        )
    if reconnect_max < reconnect_min:
        raise ConfigError(
            f"RECONNECT_MAX_SECONDS ({reconnect_max}) cannot be below "
            f"RECONNECT_MIN_SECONDS ({reconnect_min})"
        )
    if status_interval <= 0:
        raise ConfigError(
            f"MARKET_STATUS_INTERVAL_SECONDS must be positive, got {status_interval}"
        )
    if stale_after <= flush_interval:
        raise ConfigError(
            f"STALE_AFTER_SECONDS ({stale_after}) must be above "
            f"FLUSH_INTERVAL_SECONDS ({flush_interval})"
        )

    return StreamConfig(
        api_key=_read_required(
            env, "FINNHUB_API_KEY", "Get a free key at finnhub.io and put it in .env"
        ),
        symbols=parse_symbols(env.get("STOCK_SYMBOLS") or DEFAULTS["STOCK_SYMBOLS"]),
        ws_url=(env.get("FINNHUB_WS_URL") or DEFAULTS["FINNHUB_WS_URL"]).rstrip("/"),
        base_url=(
            env.get("FINNHUB_BASE_URL") or DEFAULTS["FINNHUB_BASE_URL"]
        ).rstrip("/"),
        timeout_seconds=timeout_seconds,
        flush_interval_seconds=flush_interval,
        flush_max_rows=flush_max_rows,
        reconnect_min_seconds=reconnect_min,
        reconnect_max_seconds=reconnect_max,
        market_status_interval_seconds=status_interval,
        stale_after_seconds=stale_after,
    )