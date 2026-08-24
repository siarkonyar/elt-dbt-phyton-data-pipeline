"""Deciding which examples go to train, validation and test."""

import hashlib

import numpy as np

TRAIN = "train"
VALIDATION = "validation"
TEST = "test"
SPLITS = (TRAIN, VALIDATION, TEST)


def _bucket(example_id, seed):
    """Map an example id to a stable number in [0, 1)."""
    digest = hashlib.sha256(f"{seed}:{example_id}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16) / 2**64


def assign_splits(frame, seed, train_ratio, val_ratio, id_column="example_id", label_column="label"):
    """Give every row a split, keeping label proportions intact."""
    if train_ratio <= 0 or val_ratio < 0 or train_ratio + val_ratio >= 1:
        raise ValueError(
            f"ratios must leave room for a test split, got "
            f"train={train_ratio}, val={val_ratio}"
        )

    bucket = frame[id_column].map(lambda example_id: _bucket(example_id, seed))

    # Where this row sits inside its OWN label group, as a fraction of it.
    position = bucket.groupby(frame[label_column]).rank(method="first", pct=True)

    split = np.select(
        [position <= train_ratio, position <= train_ratio + val_ratio],
        [TRAIN, VALIDATION],
        default=TEST,
    )
    return frame.assign(split=split)