import os
from pathlib import Path

from sqlalchemy import create_engine

from queries import GET_CANDLES_SQL, GET_USER_SQL, INSERT_USER_SQL

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

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
            "Check that docker-compose.yaml passes ./.env to the api service."
        )

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    return create_engine(url)

def read_candles(engine, symbol, hours):
    with engine.connect() as connection:
        return connection.execute(
            GET_CANDLES_SQL, {"symbol": symbol, "hours": hours}
        ).all()

def apply_schema(connection):
    """Run the CREATE TABLE IF NOT EXISTS statements in schema.sql."""
    connection.exec_driver_sql(SCHEMA_PATH.read_text(encoding="utf-8"))

def read_user(connection, username):
    return connection.execute(
        GET_USER_SQL, {"username": username}
    ).one_or_none()

def create_user(connection, username, password_hash, role):
    return connection.execute(
        INSERT_USER_SQL,
        {"username": username, "password_hash": password_hash, "role": role},
    ).scalar()
