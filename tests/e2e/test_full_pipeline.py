"""fake_websocket -> stream -> raw_trades -> rollup -> candles -> dashboard SQL"""

import pytest
import requests
from sqlalchemy import text

SYMBOL = "NVDA"
OTHER_SYMBOL = "AMZN"

NVDA_TRADES = 4                            # four NVDA trades in one minute
ALL_TRADES = 5                             # plus the single AMZN one
EXPECTED_OHLC = (100.0, 108.0, 95.0, 104.0)

CANDLE_WINDOW_HOURS = 1
DASHBOARD_HEALTH_PATH = "/_stcore/health"
DASHBOARD_TIMEOUT_SECONDS = 10

OTHER_CANDLES_SQL = text("SELECT count(*) FROM candles WHERE symbol = :symbol")
STREAM_TRADES_SQL = text("SELECT sum(trades_received) FROM stream_sessions")
ROLLUP_OK_SQL = text("SELECT count(*) FROM rollup_runs WHERE status = 'ok'")

#this is written here because we want to call the nvidia cande only once throughout this session.
#rand it is not going in the config file because we are gonna use it only in this file
@pytest.fixture(scope="session")
def nvda_candle(wait_for_candle):
    """Blocks until the pipeline has delivered a COMPLETE candle.

    Every test below depends on this, so the waiting happens exactly once
    and each assertion afterwards is deterministic.
    """
    return wait_for_candle(SYMBOL, NVDA_TRADES)


def test_stream_container_received_the_trades(nvda_candle, e2e_engine):
    """Summed, not '== 5 on one row': if the socket dropped and reconnected
    the count is split over two sessions, and that must not fail the test."""
    with e2e_engine.connect() as connection:
        total = connection.execute(STREAM_TRADES_SQL).scalar()

    assert total >= ALL_TRADES

def test_rollup_container_completed_a_run(nvda_candle, e2e_engine):
    with e2e_engine.connect() as connection:
        ok_runs = connection.execute(ROLLUP_OK_SQL).scalar()

    assert ok_runs >= 1

def test_candle_has_the_expected_ohlc(nvda_candle):
    """The whole chain worked: four trades became one correct candle."""
    prices = (
        float(nvda_candle.open),
        float(nvda_candle.high),
        float(nvda_candle.low),
        float(nvda_candle.close),
    )

    assert prices == EXPECTED_OHLC
    assert nvda_candle.trade_count == NVDA_TRADES

def test_second_symbol_also_produces_a_candle(nvda_candle, e2e_engine):
    """Nothing along the path is accidentally hardcoded to one symbol."""
    with e2e_engine.connect() as connection:
        count = connection.execute(
            OTHER_CANDLES_SQL, {"symbol": OTHER_SYMBOL}
        ).scalar()

    assert count == 1

def test_dashboard_query_returns_the_candle(
    nvda_candle, e2e_engine, dashboard_queries
):
    """Runs the dashboard's own SQL against the data the pipeline produced."""
    with e2e_engine.connect() as connection:
        rows = connection.execute(
            dashboard_queries.CANDLES_SQL, {"hours": CANDLE_WINDOW_HOURS}
        ).all()

    assert any(row.symbol == SYMBOL for row in rows)


def test_dashboard_image_answers_health_check(nvda_candle, compose):
    """Proves the image starts and stays up. It does NOT prove the chart
    drew — Streamlit renders over its own websocket, so plain HTTP can
    never see it. Depends on nvda_candle only for the delay: by then
    Streamlit has certainly finished starting.
    """
    host = compose.get_service_host("dashboard", 8501)
    port = compose.get_service_port("dashboard", 8501)

    response = requests.get(
        f"http://{host}:{port}{DASHBOARD_HEALTH_PATH}",
        timeout=DASHBOARD_TIMEOUT_SECONDS,
    )

    assert response.status_code == 200