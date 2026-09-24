CREATE TABLE IF NOT EXISTS users (
    user_id         BIGSERIAL   PRIMARY KEY,
    username        TEXT        NOT NULL UNIQUE,
    password_hash   TEXT        NOT NULL UNIQUE,
    role            TEXT        NOT NULL DEFAULT 'user', CHECK (role IN ('admin','user'))
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
);