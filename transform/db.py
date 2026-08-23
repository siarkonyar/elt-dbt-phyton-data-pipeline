from sqlalchemy import create_engine
import pandas as pd
import os

#environment variables.
HOST = os.environ.get("DESTINATION_POSTGRES_HOST", "destination_postgres")
PORT = os.environ.get("DESTINATION_POSTGRES_PORT", "5432")
DB_NAME = os.environ.get("DESTINATION_POSTGRES_DB", "destination_db")
USER = os.environ.get("DESTINATION_POSTGRES_USER", "postgres")
PASSWORD = os.environ.get("DESTINATION_POSTGRES_PASSWORD")