import os
from pathlib import Path

from sqlalchemy import create_engine, text

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

ALERT_TO_EMAIL_SQL = text(
  """
    SELECT a.alert_id, u.email, a.symbol, a.direction, a.threshold,
           a.triggered_price, a.triggered_at
      FROM price_alerts AS a
      JOIN users AS u ON u.user_id = a.user_id
    WHERE a.alert_id = :alert_id
      AND a.triggered_at IS NOT NULL
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
            "Check that docker-compose.yaml passes ./.env to the worker service."
        )

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    return create_engine(url)


def apply_schema(connection, schema_path=SCHEMA_PATH):
    """Run the CREATE TABLE IF NOT EXISTS statements in schema.sql."""
    connection.exec_driver_sql(schema_path.read_text(encoding="utf-8"))


def read_alert_to_email(connection, alert_id):
    return connection.execute(ALERT_TO_EMAIL_SQL, {"alert_id": alert_id}).one_or_none()


