import time
from dataclasses import dataclass
from urllib.parse import urlencode
from typing import Any, Callable
from config import MAX_PAGE_SIZE
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

USER_AGENT = "siar-elt-ingest/1.0"

def build_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session

@dataclass(frozen=True)
class HfDatasetsClient:
    session: Any
    text_column: str
    label_column: str
    timeout_seconds: float
    max_retries: int
    base_url: str = BASE_URL
    sleep: Callable = time.sleep

    def _decode(self, response, url):
        try:
            return response.json()
        except ValueError as error:
            raise HfApiError(
                f"{url} returned HTTP 200 but the body is not JSON: "
                f"{response.text[:200]}"
            ) from error

    def _get(self, path, params):
        """GET a JSON document, retrying only the failures worth retrying."""
        url = f"{self.base_url}/{path}?{urlencode(params)}"
        last_problem = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as error:
                last_problem = f"{type(error).__name__}: {error}"
            else:
                if response.status_code == 200:
                    return self._decode(response, url), url

                if response.status_code not in RETRY_STATUS_CODES:
                    raise HfApiError(
                        f"{url} returned HTTP {response.status_code}, "
                        f"which will not change on a retry: {response.text[:200]}"
                    )

                last_problem = f"HTTP {response.status_code}: {response.text[:200]}"

            if attempt < self.max_retries:
                self.sleep(BACKOFF_BASE_SECONDS * 2**attempt)

        raise HfApiError(
            f"{url} failed {self.max_retries + 1} times. Last problem: {last_problem}"
        )

    def fetch_page(self, dataset_name, dataset_config, split, offset, length):
        """Fetch one page of rows and return it in our own shape."""
        if length > MAX_PAGE_SIZE:
            raise ValueError(
                f"length must not be greater than {MAX_PAGE_SIZE} "
                f"(the API's cap), got {length}"
            )

        payload, url = self._get(
            "rows",
            {
                "dataset": dataset_name,
                "config": dataset_config,
                "split": split,
                "offset": offset,
                "length": length,
            },
        )

        for key in ("rows", "features", "num_rows_total"):
            if key not in payload:
                raise HfApiError(
                    f"{url} returned JSON without {key!r}; "
                    f"got keys {sorted(payload)}"
                )

        return Page(
            rows=parse_rows(payload["rows"], self.text_column, self.label_column),
            num_rows_total=payload["num_rows_total"],
            label_names=parse_label_names(payload["features"], self.label_column),
            url=url,
        )

    def fetch_splits(self, dataset_name):
        """Return the (config, split) pairs this dataset offers."""
        payload, url = self._get("splits", {"dataset": dataset_name})

        if "splits" not in payload:
            raise HfApiError(
                f"{url} returned JSON without 'splits'; got keys {sorted(payload)}"
            )

        return tuple(
            (entry.get("config"), entry.get("split")) for entry in payload["splits"]
        )
