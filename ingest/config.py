import os
from dataclasses import dataclass

MAX_PAGE_SIZE = 100

STRIDED = "strided"#by skipping to get variance from the dataset
SEQUENTIAL = "sequential"#by order
SAMPLING_STRATEGIES = (STRIDED, SEQUENTIAL)

DEFAULTS = {
    "HF_DATASET": "fancyzhx/ag_news",
    "HF_CONFIG": "default",
    "HF_SPLIT": "train",
    "HF_TEXT_COLUMN": "text",
    "HF_LABEL_COLUMN": "label",
    "INGEST_TARGET_ROWS": "2000",
    "INGEST_PAGE_SIZE": "100",
    "INGEST_SAMPLING": STRIDED,
    "HF_TIMEOUT_SECONDS": "30",
    "HF_MAX_RETRIES": "5",
}

class ConfigError(RuntimeError):
    """Raised when a setting is missing, unparseable, or out of range."""


@dataclass(frozen=True) #creates the constructor automatically
class IngestConfig:
    dataset_name: str
    dataset_config: str
    split: str
    text_column: str
    label_column: str
    target_rows: int
    page_size: int
    sampling: str
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

  target_rows = _read_number(env, "INGEST_TARGET_ROWS", int)
  page_size = _read_number(env, "INGEST_PAGE_SIZE", int)
  timeout_seconds = _read_number(env, "HF_TIMEOUT_SECONDS", float)
  max_retries = _read_number(env, "HF_MAX_RETRIES", int)
  sampling = env.get("INGEST_SAMPLING", DEFAULTS["INGEST_SAMPLING"])

  if target_rows < 1:
      raise ConfigError(f"INGEST_TARGET_ROWS must be at least 1, got {target_rows}")

  if not 1 <= page_size <= MAX_PAGE_SIZE:
      raise ConfigError(
          f"INGEST_PAGE_SIZE must be between 1 and {MAX_PAGE_SIZE} "
          f"(the API's own cap), got {page_size}"
      )

  if sampling not in SAMPLING_STRATEGIES:
      raise ConfigError(
          f"INGEST_SAMPLING must be one of {list(SAMPLING_STRATEGIES)}, "
          f"got {sampling!r}"
      )

  if timeout_seconds <= 0:
      raise ConfigError(f"HF_TIMEOUT_SECONDS must be positive, got {timeout_seconds}")

  if max_retries < 0:
      raise ConfigError(f"HF_MAX_RETRIES cannot be negative, got {max_retries}")

  return IngestConfig(
      dataset_name=env.get("HF_DATASET", DEFAULTS["HF_DATASET"]),
      dataset_config=env.get("HF_CONFIG", DEFAULTS["HF_CONFIG"]),
      split=env.get("HF_SPLIT", DEFAULTS["HF_SPLIT"]),
      text_column=env.get("HF_TEXT_COLUMN", DEFAULTS["HF_TEXT_COLUMN"]),
      label_column=env.get("HF_LABEL_COLUMN", DEFAULTS["HF_LABEL_COLUMN"]),
      target_rows=target_rows,
      page_size=page_size,
      sampling=sampling,
      timeout_seconds=timeout_seconds,
      max_retries=max_retries,
  )