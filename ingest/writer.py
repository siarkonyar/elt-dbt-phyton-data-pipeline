from sqlalchemy import text

#this prevents SQL injections with placeholders
INSERT_SQL = text(
    """
    INSERT INTO raw_dataset_rows
        (dataset, config, split, row_idx, text, label, label_name, source_url)
    VALUES
        (:dataset, :config, :split, :row_idx, :text, :label, :label_name, :source_url)
    ON CONFLICT (dataset, config, split, row_idx) DO NOTHING
    """
)

COUNT_SQL = text(
    """
    SELECT count(*) FROM raw_dataset_rows
    WHERE dataset = :dataset AND config = :config AND split = :split
    """
)

def count_landed_rows(connection, dataset_name, dataset_config, split):
    return connection.execute(
        COUNT_SQL,
        {"dataset": dataset_name, "config": dataset_config, "split": split},
    ).scalar_one()

def _label_name(label_names, label):
    if not isinstance(label, int) or not 0 <= label < len(label_names):
        return None
    return label_names[label]

def upsert_rows(connection, dataset_name, dataset_config, split, page):
    """Insert a page's rows, skipping any we already have. Returns rows inserted."""
    if not page.rows:
        return 0

    payload = [
        {
            "dataset": dataset_name,
            "config": dataset_config,
            "split": split,
            "row_idx": row.row_idx,
            "text": row.text,
            "label": row.label,
            "label_name": _label_name(page.label_names, row.label),
            "source_url": page.url,
        }
        for row in page.rows
    ]

    before = count_landed_rows(connection, dataset_name, dataset_config, split)
    connection.execute(INSERT_SQL, payload)
    after = count_landed_rows(connection, dataset_name, dataset_config, split)

    return after - before