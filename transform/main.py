import hashlib
import os
from datetime import datetime, timezone

import pandas as pd

from checks import run_all_checks
from clean import add_text_stats, normalize_text
from db import get_engine, read_table, write_table
from dedup import content_hash, drop_duplicate_texts
from split import assign_splits

SPLIT_SEED = os.environ.get("SPLIT_SEED", "42")
TRAIN_RATIO = float(os.environ.get("TRAIN_RATIO", "0.8"))
VAL_RATIO = float(os.environ.get("VAL_RATIO", "0.1"))
MIN_WORD_COUNT = int(os.environ.get("MIN_WORD_COUNT", "3"))
MAX_WORD_COUNT = int(os.environ.get("MAX_WORD_COUNT", "5000"))
MIN_CLASS_SHARE = float(os.environ.get("MIN_CLASS_SHARE", "0.10"))

EXAMPLE_COLUMNS = [
    "example_id", "text_clean", "label", "label_name",
    "char_count", "word_count", "split", "source_row_idx",
]

def build_dataset(raw):
    # raw_dataset_rows already has a column called `split` (the Hugging Face
    # split we pulled from). assign_splits is about to create its own `split`
    # column, so rename the source one out of the way first.
    frame = raw.rename(columns={"split": "source_split", "row_idx": "source_row_idx"})

    frame = frame.assign(text_clean=normalize_text(frame["text"]))
    frame = add_text_stats(frame)#adds columns for text stats to the dataframe

    #filters the frame, eliminates too short or too long texts
    before = len(frame)
    frame = frame[frame["text_clean"].str.len() > 0]
    frame = frame[frame["word_count"].between(MIN_WORD_COUNT, MAX_WORD_COUNT)]
    print(f"  filtered: {before} -> {len(frame)} rows")

    frame = frame.assign(example_id=content_hash(frame["text_clean"]))

    #filter duplicates
    before = len(frame)
    frame = drop_duplicate_texts(frame, order_column="source_row_idx")
    print(f"  deduplicated: {before} -> {len(frame)} rows")

    frame = assign_splits(frame, SPLIT_SEED, TRAIN_RATIO, VAL_RATIO)
    return frame[EXAMPLE_COLUMNS]

def build_version(examples, raw):
    fingerprint = hashlib.sha256(
        "".join(sorted(examples["example_id"])).encode("utf-8")
    ).hexdigest()

    counts = examples["split"].value_counts()

    return pd.DataFrame([{
        "version_id": fingerprint[:12],
        "dataset": raw["dataset"].iloc[0],
        "dataset_config": raw["config"].iloc[0],
        "source_split": raw["split"].iloc[0],
        "built_at": datetime.now(timezone.utc),
        "n_raw_rows": len(raw),
        "n_examples": len(examples),
        "n_train": int(counts.get("train", 0)),
        "n_validation": int(counts.get("validation", 0)),
        "n_test": int(counts.get("test", 0)),
        "n_labels": int(examples["label_name"].nunique()),
        "fingerprint": fingerprint,
        "split_seed": SPLIT_SEED,
        "train_ratio": TRAIN_RATIO,
        "val_ratio": VAL_RATIO,
        "min_word_count": MIN_WORD_COUNT,
        "max_word_count": MAX_WORD_COUNT,
    }])

def main():
    engine = get_engine()

    print("Reading raw_dataset_rows...")
    raw = read_table(engine, "raw_dataset_rows")
    if raw.empty:
        raise RuntimeError(
            "raw_dataset_rows is empty -- run the ingest service first"
        )
    print(f"  {len(raw)} raw rows")

    print("Building dataset...")
    examples = build_dataset(raw)
    version = build_version(examples, raw)

    # Nothing has touched the database yet. We only write once every table has
    # been built AND verified, so a bad dataset never reaches disk.
    print("Running data-quality checks...")
    run_all_checks(examples, TRAIN_RATIO, VAL_RATIO, MIN_CLASS_SHARE)

    print("Writing tables...")
    for name, frame in [("dataset_examples", examples), ("dataset_version", version)]:
        write_table(engine, frame, name)
        print(f"  wrote {name}: {len(frame)} rows")

    print("Transform finished.")


if __name__ == "__main__":
    main()