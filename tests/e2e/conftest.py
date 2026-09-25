"""Fixtures for the container-level end-to-end test.

Nothing here imports the services. That is the whole point of this tier:
the code under test runs inside its real image and is reached over a
socket, exactly the way it is reached in production.
"""

import time
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from testcontainers.compose import DockerCompose

ROOT = Path(__file__).resolve().parents[2]

# Order matters: relative paths inside these files resolve against the
# directory of the FIRST one, which is the repo root.
COMPOSE_FILES = ["docker-compose.yaml", "tests/e2e/docker-compose.e2e.yaml"]

# Matches POSTGRES_PASSWORD in docker-compose.e2e.yaml.
TEST_PASSWORD = "e2e"
DSN = "postgresql+psycopg2://postgres:{password}@{host}:{port}/destination_db"

POLL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 120

DIAGNOSTIC_TABLES = (
    "raw_trades",
    "candles",
    "rollup_runs",
    "stream_sessions",
    "users",
)
DIAGNOSTIC_SERVICES = ("fake_websocket", "stream", "rollup", "api")

NEWEST_CANDLE_SQL = text(
    "SELECT * FROM candles WHERE symbol = :symbol ORDER BY minute DESC LIMIT 1"
)

ALERT_SQL = text("SELECT * FROM price_alerts WHERE alert_id = :alert_id")

API_PORT = 8000
API_TIMEOUT_SECONDS = 10

# Matches API_ADMIN_USERNAME / API_ADMIN_PASSWORD in docker-compose.e2e.yaml.
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "e2e-admin-password"

USER_USERNAME = "plain-user"
USER_PASSWORD = "a-plain-password"

# The api has to finish its lifespan - create the users table and seed the
# admin - before the first login can possibly work.
LOGIN_TIMEOUT_SECONDS = 60


@pytest.fixture(scope="session")
def compose():
    """The real stack, built fresh, torn down whatever happens.

    build=True on every run: a stale image would let this test pass on
    code that is no longer in the repo. Docker's layer cache makes the
    second build cheap.

    `with` matters — it guarantees `docker compose down` even when a test
    fails or you hit Ctrl-C. testcontainers removes the volumes too, so
    the next run starts from an empty database.
    """
    stack = DockerCompose(
        context=ROOT,
        compose_file_name=COMPOSE_FILES,
        build=True,
    )
    with stack:
        yield stack


@pytest.fixture(scope="session")
def e2e_engine(compose):
    """Connects on whatever host port Docker happened to pick."""
    host = compose.get_service_host("destination_postgres", 5432)
    port = compose.get_service_port("destination_postgres", 5432)

    engine = create_engine(DSN.format(password=TEST_PASSWORD, host=host, port=port))
    yield engine
    engine.dispose()


def _row_counts(engine):
    lines = []
    for table in DIAGNOSTIC_TABLES:
        try:
            # A fresh connection per table: one failed statement poisons
            # its transaction, and every later count would fail too.
            # The f-string is safe here — DIAGNOSTIC_TABLES is a constant
            # we wrote, never user input.
            with engine.connect() as connection:
                count = connection.execute(
                    text(f"SELECT count(*) FROM {table}")
                ).scalar()
        except SQLAlchemyError as error:
            count = f"unreadable ({type(error).__name__})"
        lines.append(f"  {table}: {count}")
    return lines


def _service_logs(compose):
    lines = []
    for service in DIAGNOSTIC_SERVICES:
        stdout, stderr = compose.get_logs(service)
        lines.append(f"----- {service} stdout -----")
        lines.append(stdout.strip() or "(empty)")
        if stderr.strip():
            lines.append(f"----- {service} stderr -----")
            lines.append(stderr.strip())
    return lines


def _diagnostics(engine, compose, symbol, trade_count):
    """A bare 'timed out after 120s' tells you nothing. This tells you where
    the journey stopped: no raw trades means the socket never delivered, raw
    trades but no candles means the rollup is the problem."""
    return "\n".join(
        [
            f"no {symbol} candle with trade_count={trade_count} after "
            f"{POLL_TIMEOUT_SECONDS}s",
            "",
            "row counts:",
            *_row_counts(engine),
            "",
            *_service_logs(compose),
        ]
    )


@pytest.fixture(scope="session")
def wait_for_candle(e2e_engine, compose):
    """Waits for a COMPLETE candle, not merely a present one."""

    def wait(symbol, trade_count):
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                with e2e_engine.connect() as connection:
                    row = connection.execute(
                        NEWEST_CANDLE_SQL, {"symbol": symbol}
                    ).first()
            except SQLAlchemyError:
                # Early on, Postgres is up but `candles` does not exist yet —
                # the services create it on their first run. Not an error,
                # just "not ready".
                row = None

            if row is not None and row.trade_count == trade_count:
                return row

            time.sleep(POLL_SECONDS)

        pytest.fail(_diagnostics(e2e_engine, compose, symbol, trade_count))

    return wait


@pytest.fixture(scope="session")
def wait_for_triggered_alert(e2e_engine, compose):
    """Waits for the rollup container to stamp one alert.

    The overlay drops the rollup interval to 5s, so this normally returns on
    the first or second poll. A timeout means the pipeline produced candles
    but the alert path never ran, so the same row counts and container logs
    the candle wait prints are what you want to see.
    """

    def wait(alert_id):
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            with e2e_engine.connect() as connection:
                row = connection.execute(ALERT_SQL, {"alert_id": alert_id}).one()

            if row.triggered_at is not None:
                return row

            time.sleep(POLL_SECONDS)

        pytest.fail(
            "\n".join(
                [
                    f"alert {alert_id} was never triggered after "
                    f"{POLL_TIMEOUT_SECONDS}s",
                    "",
                    "row counts:",
                    *_row_counts(e2e_engine),
                    "",
                    *_service_logs(compose),
                ]
            )
        )

    return wait


@pytest.fixture(scope="session")
def api_url(compose):
    """Builds a url on whatever host port Docker picked for the api.

    A fixture rather than a plain helper, because the token fixtures below need
    it too and they cannot reach a function defined in a test module.
    """

    def url(path):
        host = compose.get_service_host("api", API_PORT)
        port = compose.get_service_port("api", API_PORT)
        return f"http://{host}:{port}{path}"

    return url


def _login(api_url, username, password):
    response = requests.post(
        api_url("/auth/login"),
        json={"username": username, "password": password},
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def admin_token(api_url):
    """The seeded admin's token, polled until the api is ready to give one.

    This is the first fixture to touch the api, so it carries the waiting. A
    single attempt would race the container's startup and fail with a confusing
    connection error on a stack that was about to be fine.
    """
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    last_problem = "never attempted"

    while time.monotonic() < deadline:
        try:
            return _login(api_url, ADMIN_USERNAME, ADMIN_PASSWORD)
        except requests.RequestException as error:
            last_problem = f"{type(error).__name__}: {error}"
        time.sleep(POLL_SECONDS)

    pytest.fail(
        f"could not sign in as {ADMIN_USERNAME} within {LOGIN_TIMEOUT_SECONDS}s "
        f"- last problem: {last_problem}"
    )


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def user_headers(api_url, admin_token):
    """A plain, self-registered account.

    Depends on admin_token only for its waiting: by the time that resolves, the
    api is up and seeded, so this can register in one attempt. A 409 is fine -
    it means a previous run in the same stack already created the account.
    """
    requests.post(
        api_url("/auth/register"),
        json={"username": USER_USERNAME, "password": USER_PASSWORD},
        timeout=API_TIMEOUT_SECONDS,
    )

    return {"Authorization": f"Bearer {_login(api_url, USER_USERNAME, USER_PASSWORD)}"}
