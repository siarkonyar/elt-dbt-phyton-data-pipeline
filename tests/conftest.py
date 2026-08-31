import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent

# The services are independent projects with no shared package. Inside its
# container the stream service has WORKDIR /app, so its modules import each
# other by bare name: `from backoff import ExponentialBackoff`.
#
# Putting stream/ on sys.path lets the tests import those modules under the
# exact same names the container uses, so we test the real import shape.
sys.path.insert(0, str(ROOT / "stream"))

import db  # noqa: E402  - stream/db.py, importable only after the line above

LOCAL_TEST_DSN = "postgresql+psycopg2://postgres:{password}@localhost:5434/test_db"


def pytest_collection_modifyitems(config, items):
    """Anything under tests/integration/ is an integration test, automatically."""
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)


def _password_from_env_file():
    """docker compose reads .env by itself; a test run on the host does not."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return None

    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "POSTGRES_PASSWORD":
            return value.strip()

    return None


def _database_url():
    """CI sets TEST_DATABASE_URL. Locally we fall back to the compose Postgres."""
    from_env = os.environ.get("TEST_DATABASE_URL")
    if from_env:
        return from_env

    password = os.environ.get("POSTGRES_PASSWORD") or _password_from_env_file()
    return LOCAL_TEST_DSN.format(password=password)


@pytest.fixture(scope="session")
def engine():
    """One engine for the whole run. Skips the integration tests if unreachable."""
    engine = create_engine(_database_url())

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Deliberately not echoing the error - it can contain the DSN.
        pytest.skip(
            "no test database on localhost:5434. Start it with:\n"
            "  docker compose up -d destination_postgres\n"
            "  docker compose exec destination_postgres createdb -U postgres test_db"
        )

    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine):
    """A connection whose work is always undone.

    Postgres makes DDL transactional too, so even CREATE TABLE disappears on
    rollback. Tests therefore cannot leak rows into one another.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def stream_db(connection):
    """A connection with the stream service's tables already created."""
    db.apply_schema(connection)
    return connection