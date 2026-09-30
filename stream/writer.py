from dataclasses import asdict

from sqlalchemy import text

INSERT_TRADES_SQL = text(
    """
    INSERT INTO raw_trades (symbol, trade_ts, price, volume, conditions)
    VALUES (:symbol, :trade_ts, :price, :volume, :conditions)
    """
)


def insert_trades(connection, trades):
    """One round trip for the whole batch. Returns rows written."""
    if not trades:
        return 0

    connection.execute(INSERT_TRADES_SQL, [asdict(trade) for trade in trades])
    return len(trades)

START_SESSION_SQL = text(
    """
    INSERT INTO stream_sessions (connected_at, symbols, reconnects, status)
    VALUES (now(), :symbols, :reconnects, 'live')
    RETURNING session_id
    """
)

def start_session(connection, symbols, reconnects):
    """One row per successful connection. Returns its session_id."""
    return connection.execute(
        START_SESSION_SQL,
        {"symbols": ",".join(symbols), "reconnects": reconnects},
    ).scalar_one()

HEARTBEAT_SQL = text(
    """
    UPDATE stream_sessions
      SET trades_received = trades_received + :trades,
          rows_written    = rows_written    + :rows,
          last_message_at = GREATEST(last_message_at, :last_message_at),
          last_trade_at   = GREATEST(last_trade_at,   :last_trade_at),
          market_open     = COALESCE(:market_open,     market_open),
          market_session  = COALESCE(:market_session,  market_session)
    WHERE session_id = :session_id
    """
)

def heartbeat(connection, session_id, **fields):
    """Runs on every flush, including flushes with zero trades."""
    connection.execute(HEARTBEAT_SQL, {"session_id": session_id, **fields})

FINISH_SESSION_SQL = text(
    """
    UPDATE stream_sessions
      SET disconnected_at = now(),
          status          = :status,
          error_message   = :error_message
    WHERE session_id = :session_id
    """
)

def finish_session(connection, session_id, status, error_message=None):
    """status is 'closed' for a clean drop, 'failed' for an error."""
    connection.execute(
        FINISH_SESSION_SQL,
        {
            "session_id": session_id,
            "status": status,
            "error_message": error_message,
        },
    )

# The trade's own time, not now(): the flush runs up to a second after the
# trade, and the alert should say when the price crossed. triggered_at IS NULL
# means an alert fires once and is never overwritten by a later trade.
MARK_TRIGGERED_SQL = text(
    """
    UPDATE price_alerts
       SET triggered_at    = :trade_ts,
           triggered_price = :price
     WHERE alert_id = :alert_id
       AND triggered_at IS NULL
    """
)

def mark_triggered(connection, fired):
    """One round trip for every alert the batch set off. Returns how many."""
    if not fired:
        return 0

    connection.execute(MARK_TRIGGERED_SQL, list(fired))
    return len(fired)
