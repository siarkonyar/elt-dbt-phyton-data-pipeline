"""this file gives every emaple a unique id by hashing. ad if any emaple shares the same example id,
it means it is duplicate and needs to be deleted"""

import hashlib


def _hash_one(text):
    return hashlib.sha256(str(text).strip().lower().encode("utf-8")).hexdigest()


def content_hash(series):
    """A fingerprint of each text: same text in, same id out, forever."""
    return series.map(_hash_one)


def drop_duplicate_texts(frame, id_column="example_id", order_column="row_idx"):
    """Keep the earliest row for each distinct text. Returns a new frame."""
    return (
        frame.sort_values(order_column)
        .drop_duplicates(subset=id_column, keep="first")
        .reset_index(drop=True)
    )