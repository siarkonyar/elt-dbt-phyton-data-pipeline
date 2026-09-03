from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from socket_client import Trade
from writer import finish_session, heartbeat, insert_trades, start_session

BASE_TIME = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_trade(symbol="NVDA", price=100.0, volume=5.0):
    return Trade(
        symbol=symbol,
        trade_ts=BASE_TIME,
        price=price,
        volume=volume,
        conditions="1,12",
    )


def heartbeat_fields(**overrides):
    """The flush loop always passes all six. Most are None most of the time."""
    fields = {
        "trades": 0,
        "rows": 0,
        "last_message_at": None,
        "last_trade_at": None,
        "market_open": None,
        "market_session": None,
    }
    return {**fields, **overrides}


def read_session(connection, session_id):
    return connection.execute(
        text("SELECT * FROM stream_sessions WHERE session_id = :id"),
        {"id": session_id},
    ).one()


# --- insert_trades ---

def test_insert_trades_writes_every_row(stream_db):
    trades = (make_trade("NVDA"), make_trade("AMZN"), make_trade("TSLA"))

    written = insert_trades(stream_db, trades)

    assert written == 3
    stored = stream_db.execute(text("SELECT count(*) FROM raw_trades")).scalar_one()
    assert stored == 3


def test_insert_trades_stores_the_values_it_was_given(stream_db):
    insert_trades(stream_db, (make_trade("NVDA", price=123.45, volume=7.0),))

    row = stream_db.execute(
        text("SELECT symbol, trade_ts, price, volume, conditions FROM raw_trades")
    ).one()

    assert row.symbol == "NVDA"
    assert float(row.price) == 123.45
    assert float(row.volume) == 7.0
    assert row.conditions == "1,12"
    assert row.trade_ts == BASE_TIME


def test_insert_trades_with_an_empty_batch_writes_nothing(stream_db):
    written = insert_trades(stream_db, ())

    assert written == 0
    assert stream_db.execute(text("SELECT count(*) FROM raw_trades")).scalar_one() == 0


# --- start_session ---

def test_start_session_returns_a_usable_id(stream_db):
    session_id = start_session(stream_db, ("NVDA", "AMZN"), reconnects=0)

    assert isinstance(session_id, int)


def test_start_session_records_the_symbols_and_marks_it_live(stream_db):
    session_id = start_session(stream_db, ("NVDA", "AMZN"), reconnects=3)

    row = read_session(stream_db, session_id)

    assert row.symbols == "NVDA,AMZN"
    assert row.reconnects == 3
    assert row.status == "live"
    assert row.disconnected_at is None


# --- heartbeat ---

def test_heartbeat_adds_to_the_running_totals(stream_db):
    session_id = start_session(stream_db, ("NVDA",), 0)

    heartbeat(stream_db, session_id, **heartbeat_fields(trades=5, rows=5))
    heartbeat(stream_db, session_id, **heartbeat_fields(trades=3, rows=2))

    row = read_session(stream_db, session_id)

    assert row.trades_received == 8
    assert row.rows_written == 7


def test_heartbeat_without_market_status_keeps_the_last_known_status(stream_db):
    session_id = start_session(stream_db, ("NVDA",), 0)
    heartbeat(
        stream_db,
        session_id,
        **heartbeat_fields(market_open=True, market_session="regular"),
    )

    # Market status is polled once a minute, so ~59 of 60 flushes pass None.
    heartbeat(stream_db, session_id, **heartbeat_fields())

    row = read_session(stream_db, session_id)

    assert row.market_open is True
    assert row.market_session == "regular"


def test_heartbeat_never_moves_last_message_at_backwards(stream_db):
    session_id = start_session(stream_db, ("NVDA",), 0)
    older = BASE_TIME - timedelta(minutes=5)

    heartbeat(stream_db, session_id, **heartbeat_fields(last_message_at=BASE_TIME))
    heartbeat(stream_db, session_id, **heartbeat_fields(last_message_at=older))

    row = read_session(stream_db, session_id)

    assert row.last_message_at == BASE_TIME


def test_heartbeat_without_a_timestamp_leaves_the_stored_one_alone(stream_db):
    session_id = start_session(stream_db, ("NVDA",), 0)

    heartbeat(stream_db, session_id, **heartbeat_fields(last_trade_at=BASE_TIME))
    heartbeat(stream_db, session_id, **heartbeat_fields(last_trade_at=None))

    row = read_session(stream_db, session_id)

    assert row.last_trade_at == BASE_TIME


# --- finish_session ---

def test_finish_session_marks_it_closed_and_stamps_the_time(stream_db):
    session_id = start_session(stream_db, ("NVDA",), 0)

    finish_session(stream_db, session_id, "closed")

    row = read_session(stream_db, session_id)

    assert row.status == "closed"
    assert row.disconnected_at is not None
    assert row.error_message is None


def test_finish_session_records_a_failure_message(stream_db):
    session_id = start_session(stream_db, ("NVDA",), 0)

    finish_session(stream_db, session_id, "failed", "ConnectionResetError: boom")

    row = read_session(stream_db, session_id)

    assert row.status == "failed"
    assert row.error_message == "ConnectionResetError: boom"