CREATE TABLE IF NOT EXISTS raw_trades (
    trade_id    BIGSERIAL   PRIMARY KEY,
    symbol      TEXT        NOT NULL,
    trade_ts    TIMESTAMPTZ NOT NULL,
    price       NUMERIC     NOT NULL,
    volume      NUMERIC,
    conditions  TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS raw_trades_symbol_ts_idx
    ON raw_trades (symbol, trade_ts DESC);

CREATE TABLE IF NOT EXISTS stream_sessions (
    session_id      BIGSERIAL   PRIMARY KEY,
    connected_at    TIMESTAMPTZ NOT NULL,
    disconnected_at TIMESTAMPTZ,
    symbols         TEXT,
    trades_received BIGINT      DEFAULT 0,
    rows_written    BIGINT      DEFAULT 0,
    last_message_at TIMESTAMPTZ,
    last_trade_at   TIMESTAMPTZ,
    reconnects      INTEGER     DEFAULT 0,
    market_open     BOOLEAN,
    market_session  TEXT,
    status          TEXT        NOT NULL,
    error_message   TEXT
);