CREATE TABLE IF NOT EXISTS users (
    user_id         BIGSERIAL   PRIMARY KEY,
    email           TEXT        NOT NULL UNIQUE,
    password_hash   TEXT        NOT NULL,
    role            TEXT        NOT NULL DEFAULT 'user'
                    CHECK (role IN ('admin', 'user')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Below users on purpose: a foreign key can only point at a table that
-- already exists. NOT NULL because a REFERENCES column on its own lets NULL
-- through, and every alert must have an owner.
CREATE TABLE IF NOT EXISTS price_alerts (
    alert_id        BIGSERIAL   PRIMARY KEY,
    user_id         BIGINT      NOT NULL REFERENCES users (user_id),
    symbol          TEXT        NOT NULL,
    direction       TEXT        NOT NULL
                    CHECK (direction IN ('above', 'below')),
    threshold       NUMERIC     NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    triggered_at    TIMESTAMPTZ,
    triggered_price NUMERIC
);
