from sqlalchemy import create_engine
import pandas as pd
import os

#environment variables.
HOST = os.environ.get("DESTINATION_POSTGRES_HOST", "destination_postgres")
PORT = os.environ.get("DESTINATION_POSTGRES_PORT", "5432")
DB_NAME = os.environ.get("DESTINATION_POSTGRES_DB", "destination_db")
USER = os.environ.get("DESTINATION_POSTGRES_USER", "postgres")
PASSWORD = os.environ.get("DESTINATION_POSTGRES_PASSWORD")

def get_engine():
  if not PASSWORD:
      raise RuntimeError(
          "DESTINATION_POSTGRES_PASSWORD is not set. "
          "Check that docker-compose.yaml passes .env to this service."
      )

  url = f"postgresql+psycopg2://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"
  return create_engine(url)

#pulls the data as DataFrame
def read_table(engine, table_name):
    return pd.read_sql(f"SELECT * FROM {table_name}", engine)

#writes the dataframe to the database
def write_table(engine, df, table_name):
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    return len(df)