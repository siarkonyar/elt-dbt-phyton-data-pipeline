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
    # Measured on `label`, not `label_name`: the name is cosmetic and is NULL
    # for datasets that do not expose ClassLabel names, which used to make this
    # check crash instead of report.
    all_labels = sorted(frame["label"].dropna().unique())
    if not all_labels:
        raise DataQualityError("no usable label values -- cannot check class balance")

    for split in SPLITS:
        rows = frame[frame["split"] == split]
        # reindex so a label that is completely absent shows up as 0.0
        # instead of quietly not existing in the counts at all.
        shares = rows["label"].value_counts(normalize=True).reindex(
            all_labels, fill_value=0.0
        )
        worst = shares.idxmin()
        if shares[worst] < min_share:
            names = frame.loc[frame["label"] == worst, "label_name"].dropna()
            shown = names.iloc[0] if len(names) else f"label {worst}"
            raise DataQualityError(
                f"class balance failed on {split!r}: {shown} is "
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
    if frame.empty:
        raise DataQualityError(
            "the dataset is empty -- every row was filtered out. "
            "Check MIN_WORD_COUNT / MAX_WORD_COUNT."
        )
    check_no_split_leakage(frame)
    check_no_empty_text(frame)
    check_class_balance(frame, min_class_share)
    check_split_ratios(frame, train_ratio, val_ratio)
    print("all data-quality checks passed")
