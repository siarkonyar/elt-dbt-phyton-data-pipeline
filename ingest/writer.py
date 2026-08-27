from dataclasses import asdict

from sqlalchemy import text

INSERT_SQL = text(
    """
    INSERT INTO raw_stock_quotes
        (symbol, quote_ts, price, day_open, day_high, day_low,
        previous_close, change, pct_change, source_url)
    VALUES
        (:symbol, :quote_ts, :price, :day_open, :day_high, :day_low,
        :previous_close, :change, :pct_change, :source_url)
    ON CONFLICT (symbol, quote_ts) DO NOTHING
    """
)

def upsert_quotes(connection, quotes):
    """Insert quotes we do not already have. Returns how many were new."""
    inserted = 0

    for quote in quotes:
        result = connection.execute(INSERT_SQL, asdict(quote))
        inserted += result.rowcount

    return inserted