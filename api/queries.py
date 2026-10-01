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
    SELECT user_id, username, password_hash, role, created_at
      FROM users
    WHERE username = :username
  """
)

INSERT_USER_SQL = text(
  """
    INSERT INTO users (username, password_hash, role)
    VALUES (:username, :password_hash, :role)
    ON CONFLICT (username) DO NOTHING
    RETURNING user_id
  """
)

# The token only carries a username, so the user_id comes from a SELECT
# instead of VALUES. No such user means no row to insert and nothing RETURNED.
INSERT_ALERT_SQL = text(
  """
    INSERT INTO price_alerts (user_id, symbol, direction, threshold)
    SELECT user_id, :symbol, :direction, :threshold
      FROM users
    WHERE username = :username
    RETURNING alert_id
  """
)

# One query for both callers: a username narrows it to that user's alerts,
# NULL (an admin) leaves every row in. The CAST gives Postgres a type for the
# parameter even when it is NULL.
LIST_ALERTS_SQL = text(
  """
    SELECT a.alert_id, u.username, a.symbol, a.direction, a.threshold,
           a.created_at, a.triggered_at, a.triggered_price
      FROM price_alerts AS a
      JOIN users AS u ON u.user_id = a.user_id
    WHERE CAST(:username AS TEXT) IS NULL OR u.username = :username
    ORDER BY a.alert_id DESC
    LIMIT :limit
  """
)

DELETE_ALERT_SQL = text(
  """
    DELETE FROM price_alerts
    WHERE alert_id = :alert_id
  """
)
