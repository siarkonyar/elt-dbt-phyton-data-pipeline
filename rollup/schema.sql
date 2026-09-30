CREATE TABLE IF NOT EXISTS candles (
    symbol      TEXT        NOT NULL,
    minute      TIMESTAMPTZ NOT NULL,
    open        NUMERIC     NOT NULL,
    high        NUMERIC     NOT NULL,
    low         NUMERIC     NOT NULL,
    close       NUMERIC     NOT NULL,
    volume      NUMERIC     NOT NULL,
    trade_count INTEGER     NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, minute)
);

-- The dashboard asks for "every symbol, last N hours". The primary key leads
-- with symbol, so it cannot serve a range scan on minute alone.
CREATE INDEX IF NOT EXISTS candles_idx ON candles (minute DESC);

CREATE TABLE IF NOT EXISTS rollup_runs (
    run_id          BIGSERIAL   PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    window_start    TIMESTAMPTZ,
    window_end      TIMESTAMPTZ,
    trades_read     BIGINT      DEFAULT 0,
    minutes_written BIGINT      DEFAULT 0,
    status          TEXT        NOT NULL,
    error_message   TEXT
);