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

API_TIMEOUT_SECONDS = 10

# Matches USER_EMAIL in tests/e2e/conftest.py.
PLAIN_EMAIL = "plain-user@example.com"

# TSLA because no other test here counts its candles - a pushed NVDA trade
# would add a second NVDA candle and break the exactly-one checks above.
LIVE_SYMBOL = "TSLA"
LIVE_THRESHOLD = 250.0
LIVE_PRICE = 260.0

#this is written here because we want to call the nvidia candle
#only once throughout this session.
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

def test_api_image_answers_health_check(nvda_candle, api_url):
    response = requests.get(api_url("/health"), timeout=API_TIMEOUT_SECONDS,)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_api_serves_the_candle_over_http(nvda_candle, api_url, admin_headers):
    response = requests.get(api_url("/candles"),
                            params={"symbol": SYMBOL, "hours": CANDLE_WINDOW_HOURS},
                            headers=admin_headers,
                            timeout=API_TIMEOUT_SECONDS,)

    assert response.status_code == 200

    candles = response.json()
    assert len(candles) == 1

    candle = candles[0]
    prices = (candle["open"], candle["high"], candle["low"], candle["close"])

    assert prices == EXPECTED_OHLC
    assert candle["trade_count"] == NVDA_TRADES

# ------------------------------------------------------------------ auth, over HTTP

READ_ALERT_SQL = text("SELECT alert_id FROM price_alerts WHERE alert_id = :alert_id")

OWNER_SQL = text(
    """
    SELECT u.email
      FROM price_alerts AS a
      JOIN users AS u ON u.user_id = a.user_id
     WHERE a.alert_id = :alert_id
    """
)

# High enough that the rollup will never fire it, so deleting it is the only
# thing that ever happens to this row.
UNREACHABLE_THRESHOLD = 999999.0


def make_alert(api_url, headers, symbol=OTHER_SYMBOL, threshold=UNREACHABLE_THRESHOLD):
    """Created the way a user creates one: over HTTP, owned by the token."""
    response = requests.post(
        api_url("/alerts"),
        json={"symbol": symbol, "direction": "above", "threshold": threshold},
        headers=headers,
        timeout=API_TIMEOUT_SECONDS,
    )

    assert response.status_code == 201
    return response.json()["alert_id"]


def list_alerts(api_url, headers):
    response = requests.get(
        api_url("/alerts"), headers=headers, timeout=API_TIMEOUT_SECONDS
    )

    assert response.status_code == 200
    return response.json()


def test_the_stream_fires_a_users_alert_live(
    nvda_candle, api_url, user_headers, push_trade, wait_for_triggered_alert
):
    """The whole feature: a user creates an alert over HTTP, a trade crosses
    it, and the real stream container stamps it.

    Depends on nvda_candle so the stream is known to be connected. The trade
    is pushed after the alert exists, because live alerts never look back.
    """
    alert_id = make_alert(
        api_url, user_headers, symbol=LIVE_SYMBOL, threshold=LIVE_THRESHOLD
    )

    push_trade(LIVE_SYMBOL, LIVE_PRICE)

    alert = wait_for_triggered_alert(alert_id)

    assert float(alert.triggered_price) == LIVE_PRICE


def test_an_alert_created_over_http_belongs_to_its_creator(
    e2e_engine, api_url, user_headers
):
    """The reason for the user_id column, checked where it lives."""
    alert_id = make_alert(api_url, user_headers)

    with e2e_engine.connect() as connection:
        owner = connection.execute(OWNER_SQL, {"alert_id": alert_id}).scalar_one()

    assert owner == PLAIN_EMAIL


def test_a_user_lists_only_their_own_alerts(api_url, user_headers, admin_headers):
    mine = make_alert(api_url, user_headers)
    someone_elses = make_alert(api_url, admin_headers)

    listed = {alert["alert_id"] for alert in list_alerts(api_url, user_headers)}

    assert mine in listed
    assert someone_elses not in listed


def test_an_admin_lists_every_users_alert(api_url, user_headers, admin_headers):
    theirs = make_alert(api_url, user_headers)

    owners = {
        alert["alert_id"]: alert["email"]
        for alert in list_alerts(api_url, admin_headers)
    }

    assert owners[theirs] == PLAIN_EMAIL


def test_the_api_refuses_a_candle_request_with_no_token(api_url):
    """The container really is closed, not just the TestClient in the unit
    tier. Nothing here is stubbed: real image, real token check."""
    response = requests.get(
        api_url("/candles"),
        params={"symbol": SYMBOL},
        timeout=API_TIMEOUT_SECONDS,
    )

    assert response.status_code == 401


def test_the_api_hands_out_a_token_for_the_seeded_admin(admin_token):
    """The admin exists at all, which means the lifespan ran inside the real
    container - schema applied and the row seeded from the compose env."""
    assert admin_token


def test_the_api_refuses_the_seeded_admin_with_a_wrong_password(api_url):
    response = requests.post(
        api_url("/auth/login"),
        json={"email": "admin@example.com", "password": "not-the-password"},
        timeout=API_TIMEOUT_SECONDS,
    )

    assert response.status_code == 401


def test_a_registered_user_may_read_the_candles(nvda_candle, api_url, user_headers):
    """Reading is not an admin power, so a self-registered account is enough."""
    response = requests.get(
        api_url("/candles"),
        params={"symbol": SYMBOL, "hours": CANDLE_WINDOW_HOURS},
        headers=user_headers,
        timeout=API_TIMEOUT_SECONDS,
    )

    assert response.status_code == 200


def test_a_registered_user_may_not_delete_an_alert(e2e_engine, api_url, user_headers):
    """403, and the row is still there afterwards. Checking only the status
    would pass against a route that answered 403 and deleted it anyway."""
    alert_id = make_alert(api_url, user_headers)

    response = requests.delete(
        api_url(f"/alerts/{alert_id}"),
        headers=user_headers,
        timeout=API_TIMEOUT_SECONDS,
    )

    assert response.status_code == 403

    with e2e_engine.connect() as connection:
        survivor = connection.execute(READ_ALERT_SQL, {"alert_id": alert_id}).one()

    assert survivor.alert_id == alert_id


def test_an_admin_deletes_an_alert_over_http(
    e2e_engine, api_url, admin_headers, user_headers
):
    """The payoff. HTTP in, SQL out: the 204 only proves the api said yes, so
    the row being gone from Postgres is what proves it happened."""
    alert_id = make_alert(api_url, user_headers)

    response = requests.delete(
        api_url(f"/alerts/{alert_id}"),
        headers=admin_headers,
        timeout=API_TIMEOUT_SECONDS,
    )

    assert response.status_code == 204

    with e2e_engine.connect() as connection:
        remaining = connection.execute(
            READ_ALERT_SQL, {"alert_id": alert_id}
        ).one_or_none()

    assert remaining is None
