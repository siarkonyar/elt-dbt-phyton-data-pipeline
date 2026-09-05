from sqlalchemy import text

import db

TABLES_SQL = text(
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
)


def table_names(connection):
    return connection.execute(TABLES_SQL).scalars().all()


def test_stream_schema_is_safe_to_apply_twice(connection):
    db.apply_schema(connection)
    db.apply_schema(connection)

    tables = table_names(connection)

    assert "raw_trades" in tables
    assert "stream_sessions" in tables


def test_rollup_schema_is_safe_to_apply_twice(connection, rollup_db):
    rollup_db.apply_schema(connection)
    rollup_db.apply_schema(connection)

    tables = table_names(connection)

    assert "candles" in tables
    assert "rollup_runs" in tables