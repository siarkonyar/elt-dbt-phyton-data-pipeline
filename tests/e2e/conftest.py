"""Fixtures for the container-level end-to-end test.

Nothing here imports the services. That is the whole point of this tier:
the code under test runs inside its real image and is reached over a
socket, exactly the way it is reached in production.
"""

import time
from pathlib import Path

import pytest
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

DIAGNOSTIC_TABLES = ("raw_trades", "candles", "rollup_runs", "stream_sessions")
DIAGNOSTIC_SERVICES = ("fake_websocket", "stream", "rollup", "api")

NEWEST_CANDLE_SQL = text(
    "SELECT * FROM candles WHERE symbol = :symbol ORDER BY minute DESC LIMIT 1"
)

ALERT_SQL = text("SELECT * FROM price_alerts WHERE alert_id = :alert_id")


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
