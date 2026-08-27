CREATE TABLE IF NOT EXISTS raw_stock_quotes (
    symbol         TEXT        NOT NULL,
    quote_ts       TIMESTAMPTZ NOT NULL,
    price          NUMERIC,
    day_open       NUMERIC,
    day_high       NUMERIC,
    day_low        NUMERIC,
    previous_close NUMERIC,
    change         NUMERIC,
    pct_change     NUMERIC,
    source_url     TEXT,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Finnhub repeats the same `t` until the price actually moves, so this
    -- key turns every duplicate poll into a no-op insert.
    PRIMARY KEY (symbol, quote_ts)
);

CREATE TABLE IF NOT EXISTS poll_runs (
    poll_id           BIGSERIAL   PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    symbols           TEXT,
    market_open       BOOLEAN,
    session           TEXT,
    requests_made     INTEGER,
    rows_inserted     INTEGER,
    throttled_seconds NUMERIC,
    retries           INTEGER,
    breaker_state     TEXT,
    status            TEXT        NOT NULL,
    error_message     TEXT
);

-- this is indexing.
CREATE INDEX IF NOT EXISTS raw_stock_quotes_ts_idx
    ON raw_stock_quotes (quote_ts DESC);