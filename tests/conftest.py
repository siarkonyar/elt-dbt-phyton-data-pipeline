import importlib.util
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
sys.path.insert(0, str(ROOT / "rollup"))
sys.path.insert(0, str(ROOT / "stream"))   # inserted last, so searched first

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

def _load_service_module(service, module_name):
    """Load rollup/<name>.py explicitly, bypassing the sys.path shadowing.

    Both services call their settings module `config`, because inside each
    container it is alone at /app. In one test process only one of them can
    own the bare name, so the other is loaded by file path instead.
    """
    full_name = f"{service}_{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    spec = importlib.util.spec_from_file_location(
        full_name, ROOT / service / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def rollup_config():
    return _load_service_module("rollup", "config")


@pytest.fixture(scope="session")
def rollup_writer():
    return _load_service_module("rollup", "writer")


@pytest.fixture(scope="session")
def rollup_db():
    return _load_service_module("rollup", "db")

@pytest.fixture
def rollup_tables(connection, rollup_db):
    rollup_db.apply_schema(connection)
    return connection