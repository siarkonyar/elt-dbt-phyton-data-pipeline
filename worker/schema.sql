CREATE TABLE IF NOT EXISTS notification_history (
    notification_id BIGSERIAL   PRIMARY KEY,
    alert_id        BIGINT      NOT NULL,
    status          TEXT        NOT NULL
                    CHECK (status IN ('sent', 'failed')),
    message_id      TEXT,
    error           TEXT,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
