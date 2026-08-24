from split import SPLITS


class DataQualityError(Exception):
    """Raised when a data-quality check fails."""


def check_no_split_leakage(frame, id_column="example_id"):
    """Every example appears exactly once, so it cannot be in two splits."""
    repeated = frame[frame[id_column].duplicated(keep=False)]
    if not repeated.empty:
        across = int((repeated.groupby(id_column)["split"].nunique() > 1).sum())
        raise DataQualityError(
            f"{repeated[id_column].nunique()} example(s) appear more than once, "
            f"{across} of them in different splits -- dedup did not hold"
        )


def check_no_empty_text(frame, column="text_clean"):
    empty = frame[frame[column].fillna("").str.strip() == ""]
    if not empty.empty:
        raise DataQualityError(f"{len(empty)} row(s) have empty {column}")


def check_class_balance(frame, min_share):
    """Every label must be present in every split, and not vanishingly rare."""
    all_labels = sorted(frame["label_name"].dropna().unique())

    for split in SPLITS:
        rows = frame[frame["split"] == split]
        # reindex so a label that is completely absent shows up as 0.0
        # instead of quietly not existing in the counts at all.
        shares = rows["label_name"].value_counts(normalize=True).reindex(
            all_labels, fill_value=0.0
        )
        worst = shares.idxmin()
        if shares[worst] < min_share:
            raise DataQualityError(
                f"class balance failed on {split!r}: {worst} is "
                f"{shares[worst]:.1%}, minimum is {min_share:.0%}"
            )


def check_split_ratios(frame, train_ratio, val_ratio, tolerance=0.05):
    expected = dict(zip(SPLITS, (train_ratio, val_ratio, 1 - train_ratio - val_ratio)))
    actual = frame["split"].value_counts(normalize=True)

    for split, want in expected.items():
        got = actual.get(split, 0.0)
        if abs(got - want) > tolerance:
            raise DataQualityError(
                f"split {split!r} is {got:.1%}, expected {want:.0%} "
                f"(tolerance ±{tolerance:.0%})"
            )


def run_all_checks(frame, train_ratio, val_ratio, min_class_share):
    check_no_split_leakage(frame)
    check_no_empty_text(frame)
    check_class_balance(frame, min_class_share)
    check_split_ratios(frame, train_ratio, val_ratio)
    print("all data-quality checks passed")
