import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

BASE_URL = "https://datasets-server.huggingface.co"

# Worth another attempt: the server is busy, or we are going too fast.
# Everything else (401, 404, 422) means the request itself is wrong and
# repeating it changes nothing.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

BACKOFF_BASE_SECONDS = 1.0

class HfApiError(RuntimeError):
    """Raised when the API cannot be reached or answers with something unusable."""


@dataclass(frozen=True)
class RawRow:
    row_idx: int
    text: str
    label: int


@dataclass(frozen=True)
class Page:
    rows: tuple
    num_rows_total: int
    label_names: tuple
    url: str

"""
This is how hugging fave sends the data
{
  "features": [
    { "name": "text",  "type": { "dtype": "string", "_type": "Value" } },
    { "name": "label", "type": { "names": ["World","Sports","Business","Sci/Tech"], "_type": "ClassLabel" } }
  ],
  "rows": [
    { "row_idx": 6000,
      "row": { "text": "Kerry Accuses Bush of...", "label": 0 },
      "truncated_cells": [] }
  ],
  "num_rows_total": 120000
}
"""

def parse_label_names(features, label_column):
    for feature in features:
        if feature.get("name") != label_column:
            continue
        return tuple(feature.get("type", {}).get("names") or ())

    available = [f.get("name") for f in features]
    raise HfApiError(
        f"label column {label_column!r} is not in this dataset; "
        f"available columns are {available}"
    )

def parse_rows(entries, text_column, label_column):
    parsed = []

    for position, entry in enumerate(entries):
        if not isinstance(entry, dict) or "row" not in entry or "row_idx" not in entry:
            raise HfApiError(
                f"row at position {position} is not shaped like "
                f"{{'row_idx': ..., 'row': ...}}, got {entry!r}"
            )

        row = entry["row"]
        for column in (text_column, label_column):
            if column not in row:
                raise HfApiError(
                    f"column {column!r} is missing from the API response; "
                    f"available columns are {sorted(row)}"
                )

        parsed.append(
            RawRow(
                row_idx=entry["row_idx"],
                text=row[text_column],
                label=row[label_column],
            )
        )

    return tuple(parsed)#tuple because it should be immutable
