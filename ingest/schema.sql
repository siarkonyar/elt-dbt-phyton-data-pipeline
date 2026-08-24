CREATE TABLE IF NOT EXISTS raw_dataset_rows (
    dataset     TEXT        NOT NULL,
    config      TEXT        NOT NULL,
    split       TEXT        NOT NULL,
    row_idx     INTEGER     NOT NULL,
    text        TEXT,
    label       INTEGER,
    label_name  TEXT,
    source_url  TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- This is why we write the DDL by hand instead of letting pandas.to_sql
    -- invent the table. to_sql creates no primary key, and without a key
    -- `INSERT ... ON CONFLICT DO NOTHING` has no conflict to detect -- so a
    -- second ingest run would happily double every row. These four columns are
    -- the natural key of a Hugging Face row, and they are the whole reason this
    -- pipeline is safe to retry.
    PRIMARY KEY (dataset, config, split, row_idx)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id         BIGSERIAL   PRIMARY KEY,
    dataset        TEXT        NOT NULL,
    config         TEXT        NOT NULL,
    split          TEXT        NOT NULL,
    sampling       TEXT,
    target_rows    INTEGER,
    num_rows_total INTEGER,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ,
    rows_fetched   INTEGER,
    rows_inserted  INTEGER,
    status         TEXT        NOT NULL,
    error_message  TEXT
);
