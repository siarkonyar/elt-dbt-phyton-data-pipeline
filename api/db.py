import os
from pathlib import Path

from sqlalchemy import create_engine

from queries import (
    DELETE_ALERT_SQL,
    GET_CANDLES_SQL,
    GET_USER_SQL,
    INSERT_ALERT_SQL,
    INSERT_USER_SQL,
    LIST_ALERTS_SQL,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# The dashboard has always shown the newest 20.
ALERT_LIST_LIMIT = 20

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

def create_alert(connection, username, symbol, direction, threshold):
    """The new alert_id, or None if that username has no account."""
    return connection.execute(
        INSERT_ALERT_SQL,
        {
            "username": username,
            "symbol": symbol,
            "direction": direction,
            "threshold": threshold,
        },
    ).scalar()

def read_alerts(connection, username):
    """One user's alerts, or everyone's when username is None."""
    return connection.execute(
        LIST_ALERTS_SQL, {"username": username, "limit": ALERT_LIST_LIMIT}
    ).all()

def delete_alert(connection, alert_id):
    return connection.execute(
        DELETE_ALERT_SQL,
        {"alert_id": alert_id},
    ).rowcount
