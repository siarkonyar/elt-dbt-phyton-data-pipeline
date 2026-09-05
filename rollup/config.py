import os
from dataclasses import dataclass

DEFAULTS = {
    "ROLLUP_INTERVAL_SECONDS": "60",
    "ROLLUP_WINDOW_MINUTES": "10",
    "ROLLUP_MAX_ROWS": "200000",
}

class ConfigError(RuntimeError):
    """Raised when a setting is missing, unparseable, or out of range."""


@dataclass(frozen=True)
class RollupConfig:
    interval_seconds: float
    window_minutes: int
    max_rows: int

def _read_number(env, name, parse):
    raw = env.get(name) or DEFAULTS[name]
    try:
        return parse(raw)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error

def load_config(env=None):
    env = os.environ if env is None else env

    interval = _read_number(env, "ROLLUP_INTERVAL_SECONDS", float)
    window = _read_number(env, "ROLLUP_WINDOW_MINUTES", int)
    max_rows = _read_number(env, "ROLLUP_MAX_ROWS", int)

    if interval <= 0:
        raise ConfigError(f"ROLLUP_INTERVAL_SECONDS must be positive, got {interval}")
    if window < 1:
        raise ConfigError(f"ROLLUP_WINDOW_MINUTES must be at least 1, got {window}")
    if max_rows < 1:
        raise ConfigError(f"ROLLUP_MAX_ROWS must be at least 1, got {max_rows}")

    # The window has to reach back at least as far as the gap between runs,
    # or minutes that pass between two runs are never aggregated at all.
    if window * 60 < interval:
        raise ConfigError(
            f"ROLLUP_WINDOW_MINUTES ({window}) covers {window * 60}s, less than "
            f"ROLLUP_INTERVAL_SECONDS ({interval}). Minutes between runs would "
            "never be rolled up."
        )

    return RollupConfig(
        interval_seconds=interval,
        window_minutes=window,
        max_rows=max_rows,
    )