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
    SELECT user_id, email, password_hash, role, created_at
      FROM users
    WHERE email = :email
  """
)

INSERT_USER_SQL = text(
  """
    INSERT INTO users (email, password_hash, role)
    VALUES (:email, :password_hash, :role)
    ON CONFLICT (email) DO NOTHING
    RETURNING user_id
  """
)

# The token only carries an email, so the user_id comes from a SELECT
# instead of VALUES. No such user means no row to insert and nothing RETURNED.
INSERT_ALERT_SQL = text(
  """
    INSERT INTO price_alerts (user_id, symbol, direction, threshold)
    SELECT user_id, :symbol, :direction, :threshold
      FROM users
    WHERE email = :email
    RETURNING alert_id
  """
)

# One query for both callers: an email narrows it to that user's alerts,
# NULL (an admin) leaves every row in. The CAST gives Postgres a type for the
# parameter even when it is NULL.
LIST_ALERTS_SQL = text(
  """
    SELECT a.alert_id, u.email, a.symbol, a.direction, a.threshold,
           a.created_at, a.triggered_at, a.triggered_price
      FROM price_alerts AS a
      JOIN users AS u ON u.user_id = a.user_id
    WHERE CAST(:email AS TEXT) IS NULL OR u.email = :email
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
