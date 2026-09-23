import importlib.util
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
    """The directory a test lives in decides its markers.

    tests/integration/ needs a real Postgres, so it carries `integration` and
    the CI job split keeps working unchanged.

    tests/e2e/ deliberately does NOT get `integration`. Those tests need
    Docker, not a database connection: the CI integration job hands them a
    lone Postgres and no compose stack, so it must not collect them.
    """
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)
        if "e2e" in item.path.parts:
            item.add_marker(pytest.mark.e2e)


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
def rollup_alerts():
    return _load_service_module("rollup", "alerts")


@pytest.fixture(scope="session")
def rollup_db():
    return _load_service_module("rollup", "db")

@pytest.fixture
def rollup_tables(connection, rollup_db):
    rollup_db.apply_schema(connection)
    return connection

def _load_with_bare_siblings(service, module_name, siblings):
    """Load <service>/<module_name>.py with its siblings under bare names.

    Inside its container a service has WORKDIR /app, so its modules import
    each other by bare name: `from queries import GET_CANDLES_SQL`. In one
    test process those bare names are shared, so the siblings are installed
    for the duration of the load and put back afterwards.

    `siblings` must be in dependency order - a module that imports another
    has to come after it.
    """
    saved = {name: sys.modules.get(name) for name in siblings}
    for name in siblings:
        sys.modules[name] = _load_service_module(service, name)

    try:
        return _load_service_module(service, module_name)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


ROLLUP_BARE_MODULES = ("candles", "config", "db", "writer", "alerts")


@pytest.fixture(scope="session")
def rollup_main():
    return _load_with_bare_siblings("rollup", "main", ROLLUP_BARE_MODULES)


@pytest.fixture(scope="session")
def dashboard_queries():
    """The dashboard's real SQL. Importing app.py instead would start
    Streamlit and open a database connection."""
    return _load_service_module("dashboard", "queries")


TRUNCATE_SQL = text(
    "TRUNCATE raw_trades, candles, rollup_runs, price_alerts RESTART IDENTITY"
)


def _empty_the_tables(engine):
    with engine.begin() as connection:
        connection.execute(TRUNCATE_SQL)


@pytest.fixture
def e2e_db(engine, rollup_db):
    with engine.begin() as connection:
        db.apply_schema(connection)          # raw_trades, stream_sessions
        rollup_db.apply_schema(connection)   # candles, rollup_runs

    _empty_the_tables(engine)  # anything a previous test left behind
    yield engine                             # an engine, not a connection
    _empty_the_tables(engine) #delete everything after the test finishes

#-----------api-----------

@pytest.fixture
def _candle_row():
    def make(**overrides):
        defaults = {
            "symbol": "NVDA",
            "minute": datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            "open": Decimal("100.0"),
            "high": Decimal("108.0"),
            "low": Decimal("95.0"),
            "close": Decimal("104.0"),
            "volume": Decimal("10.0"),
            "trade_count": 4,
        }
        return SimpleNamespace(**{**defaults, **overrides})

    return make

@pytest.fixture(scope="session")
def api_serialize():
    return _load_service_module("api", "serialize")

@pytest.fixture(scope="session")
def api_queries():
    return _load_service_module("api", "queries")

@pytest.fixture(scope="session")
def api_db():
    """db.py does `from queries import ...`, so queries has to be in place."""
    return _load_with_bare_siblings("api", "db", ("queries",))

@pytest.fixture(scope="session")
def api_config():
    return _load_service_module("api", "config")


# queries before db: db imports it, and a sibling cannot be loaded before
# the module it depends on.
API_BARE_MODULES = ("queries", "serialize", "db")


@pytest.fixture(scope="session")
def api_main():
    return _load_with_bare_siblings("api", "main", API_BARE_MODULES)
