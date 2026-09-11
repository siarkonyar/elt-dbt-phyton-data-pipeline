import os

from sqlalchemy import create_engine

from queries import GET_CANDLES_SQL


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
