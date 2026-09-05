import os

from sqlalchemy import create_engine, inspect


def _build_engine(prefix, default_host, default_db):
    host = os.environ.get(f"{prefix}_POSTGRES_HOST", default_host)
    port = os.environ.get(f"{prefix}_POSTGRES_PORT", "5432")
    db_name = os.environ.get(f"{prefix}_POSTGRES_DB", default_db)
    user = os.environ.get(f"{prefix}_POSTGRES_USER", "postgres")
    password = os.environ.get(f"{prefix}_POSTGRES_PASSWORD")

    if not password:
        raise RuntimeError(
            f"{prefix}_POSTGRES_PASSWORD is not set. "
            "Check that docker-compose.yaml passes ./.env to the "
            "dashboard service."
        )

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    return create_engine(url)


def get_destination_engine():
    return _build_engine("DESTINATION", "destination_postgres", "destination_db")


def table_exists(engine, table_name):
    return inspect(engine).has_table(table_name)
