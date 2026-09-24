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

GET_USER_SQL = text(
  """
    SELECT user_id, username, password_hash, role, updated_at
      FROM users
    WHERE username = :username
  """
)

INSERT_USER_SQL = text(
  """
    INSERT INTO users (username, password_hash, role)
    VALUES (:username, :password_hash, :role)
  """
)