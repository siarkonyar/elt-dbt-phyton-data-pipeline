CREATE TABLE IF NOT EXISTS raw_stock_quotes (
    symbol              TEXT        NOT NULL,
    quote_ts            TIMESTAMPTZ NOT NULL,
    price               NUMERIC,
    previous_close      NUMERIC,
    day_high            NUMERIC,
    day_low             NUMERIC,
    volume              BIGINT,
    fifty_two_week_high NUMERIC,
    fifty_two_week_low  NUMERIC,
    currency            TEXT,
    short_name          TEXT,
    exchange            TEXT,
    market_open         BOOLEAN,
    source_url          TEXT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Yahoo repeats the same regularMarketTime until the price actually
    -- moves, so this key turns every duplicate poll into a no-op insert.
    PRIMARY KEY (symbol, quote_ts)
);

CREATE TABLE IF NOT EXISTS poll_runs (
    poll_id           BIGSERIAL   PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    symbols           TEXT,
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