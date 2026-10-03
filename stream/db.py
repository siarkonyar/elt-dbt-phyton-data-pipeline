import os
from pathlib import Path

from sqlalchemy import create_engine, text

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# price_alerts is created by the api, not by schema.sql here. Only the api can
# create alerts, so until it has started there is nothing to wait for anyway.
PENDING_ALERTS_SQL = text(
    """
    SELECT alert_id, symbol, direction, threshold
      FROM price_alerts
     WHERE triggered_at IS NULL
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
            "Check that docker-compose.yaml passes ./.env to the stream service."
        )

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    return create_engine(url)


def apply_schema(connection, schema_path=SCHEMA_PATH):
    """Run the CREATE TABLE IF NOT EXISTS statements in schema.sql."""
    connection.exec_driver_sql(schema_path.read_text(encoding="utf-8"))


def read_pending_alerts(connection):
    return connection.execute(PENDING_ALERTS_SQL).all()
