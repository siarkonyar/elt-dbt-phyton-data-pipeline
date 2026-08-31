import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

RECENT_TRADES_SQL = text(
    """
    SELECT symbol, trade_ts, price, volume
      FROM raw_trades
     WHERE trade_ts >= :window_start
     ORDER BY symbol, trade_ts
     LIMIT :max_rows
    """
)


def get_engine(env=None):
    env = os.environ if env is None else env

    host = env.get("DESTINATION_POSTGRES_HOST", "destination_postgres")
    port = env.get("DESTINATION_POSTGRES_PORT", "5432")
    db_name = env.get("DESTINATION_POSTGRES_DB", "destination_db")
    user = env.get("DESTINATION_POSTGRES_USER", "postgres")
    password = env.get("DESTINATION_POSTGRES_PASSWORD")

    if not password:
        raise RuntimeError(
            "DESTINATION_POSTGRES_PASSWORD is not set. "
            "Check that docker-compose.yaml passes ./.env to the rollup service."
        )

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    return create_engine(url)


def apply_schema(connection):
    """Run the CREATE TABLE IF NOT EXISTS statements in schema.sql."""
    connection.exec_driver_sql(SCHEMA_PATH.read_text(encoding="utf-8"))


def read_recent_trades(connection, window_start, max_rows):
    """The trailing window as a DataFrame. Empty frame when there is nothing.

    LIMIT is a safety net, not a paging mechanism - hitting it means the
    window is configured too wide, and the run will be short some symbols.
    """
    return pd.read_sql(
        RECENT_TRADES_SQL,
        connection,
        params={"window_start": window_start, "max_rows": max_rows},
    )