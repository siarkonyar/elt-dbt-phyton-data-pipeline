from datetime import datetime, timezone

from sqlalchemy import text

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"

MAX_ERROR_LENGTH = 2000

START_SQL = text(
    """
    INSERT INTO poll_runs (symbols, started_at, status)
    VALUES (:symbols, :started_at, :status)
    RETURNING poll_id
    """
)

FINISH_SQL = text(
    """
    UPDATE poll_runs
      SET finished_at       = :finished_at,
          market_open       = :market_open,
          session           = :session,
          requests_made     = :requests_made,
          rows_inserted     = :rows_inserted,
          throttled_seconds = :throttled_seconds,
          retries           = :retries,
          breaker_state     = :breaker_state,
          status            = :status,
          error_message     = :error_message
      WHERE poll_id = :poll_id
    """
)

def _now():
    return datetime.now(timezone.utc)


def start_poll(connection, symbols):
    """Write the 'running' row before any work begins, and return its id."""
    return connection.execute(
        START_SQL,
        {
            "symbols": ",".join(symbols),
            "started_at": _now(),
            "status": RUNNING,
        },
    ).scalar_one()


def finish_poll(
    connection,
    poll_id,
    status,
    market_open=None,
    session=None,
    requests_made=0,
    rows_inserted=0,
    throttled_seconds=0.0,
    retries=0,
    breaker_state=None,
    error_message=None,
):
    """Close out a poll. Called on both the success and the failure path."""
    connection.execute(
        FINISH_SQL,
        {
            "poll_id": poll_id,
            "finished_at": _now(),
            "market_open": market_open,
            "session": session,
            "requests_made": requests_made,
            "rows_inserted": rows_inserted,
            "throttled_seconds": throttled_seconds,
            "retries": retries,
            "breaker_state": breaker_state,
            "status": status,
            "error_message": error_message[:MAX_ERROR_LENGTH] if error_message else None,
        },
    )