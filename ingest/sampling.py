import math
from config import SEQUENTIAL, STRIDED

def plan_offsets(num_rows_total, target_rows, page_size, strategy):
    """Return the list of `offset` values to ask the API for."""
    if page_size < 1:
        raise ValueError(f"page_size must be at least 1, got {page_size}")

    if strategy not in (STRIDED, SEQUENTIAL):
        raise ValueError(f"unknown sampling strategy {strategy!r}")

    if num_rows_total < 1 or target_rows < 1:
        return []

    pages_available = math.ceil(num_rows_total / page_size)
    pages_wanted = math.ceil(target_rows / page_size)
    pages_to_fetch = min(pages_wanted, pages_available)

    if strategy == SEQUENTIAL:
        return [page * page_size for page in range(pages_to_fetch)]

    # Spread the pages we want evenly across every page that exists. The stride
    # stays fractional on purpose: integer division rounds down at every step
    # and leaves the tail of the dataset unreachable.
    stride = pages_available / pages_to_fetch
    return [int(page * stride) * page_size for page in range(pages_to_fetch)]