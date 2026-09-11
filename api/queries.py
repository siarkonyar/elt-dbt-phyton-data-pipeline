from sqlalchemy import text

GET_CANDLES_SQL = text(
  """
  SELECT symbol, minute, open, high, low, close, volume, trade_count
    FROM candles
  WHERE symbol = :symbol
    AND minute >= now() - make_interval(hours => :hours)
  ORDER BY minute
  """
)
