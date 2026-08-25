"""The ingestion_runs log: one row per run, written even when the run fails."""

from datetime import datetime, timezone

from sqlalchemy import text

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"

# Tracebacks can be enormous; the first couple of thousand characters
# always contain the actual cause.
MAX_ERROR_LENGTH = 2000

START_SQL = text(
    """
    INSERT INTO ingestion_runs
        (dataset, config, split, sampling, target_rows, started_at, status)
    VALUES
        (:dataset, :config, :split, :sampling, :target_rows, :started_at, :status)
    RETURNING run_id
    """
)

FINISH_SQL = text(
    """
    UPDATE ingestion_runs
      SET finished_at    = :finished_at,
          num_rows_total = :num_rows_total,
          rows_fetched   = :rows_fetched,
          rows_inserted  = :rows_inserted,
          status         = :status,
          error_message  = :error_message
    WHERE run_id = :run_id
    """
)

def _now():
    return datetime.now(timezone.utc)


def start_run(connection, config):
    """Write the 'running' row before any work begins, and return its id."""
    return connection.execute(
        START_SQL,
        {
            "dataset": config.dataset_name,
            "config": config.dataset_config,
            "split": config.split,
            "sampling": config.sampling,
            "target_rows": config.target_rows,
            "started_at": _now(),
            "status": RUNNING,
        },
    ).scalar_one()


def finish_run(
    connection,
    run_id,
    status,
    num_rows_total=None,
    rows_fetched=0,
    rows_inserted=0,
    error_message=None,
):
    """Close out a run. Called on both the success and the failure path."""
    connection.execute(
        FINISH_SQL,
        {
            "run_id": run_id,
            "finished_at": _now(),
            "num_rows_total": num_rows_total,
            "rows_fetched": rows_fetched,
            "rows_inserted": rows_inserted,
            "status": status,
            "error_message": error_message[:MAX_ERROR_LENGTH] if error_message else None,
        },
    )