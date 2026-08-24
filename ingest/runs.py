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