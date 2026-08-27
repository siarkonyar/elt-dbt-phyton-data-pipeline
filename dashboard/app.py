import os

import pandas as pd
import streamlit as st
from sqlalchemy import text

from db import get_destination_engine, table_exists

st.set_page_config(page_title="Live stocks", page_icon="📈", layout="wide")

HISTORY_HOURS = int(os.environ.get("HISTORY_HOURS", "24"))
REFRESH = "15s"
CACHE_TTL = 10

# One row per symbol: the newest quote we hold. DISTINCT ON is the Postgres
# shortcut for "first row of each group" and rides the (symbol, quote_ts)
# primary key, so it stays fast as the table grows.
LATEST_SQL = text(
    """
    SELECT DISTINCT ON (symbol)
          symbol, quote_ts, price, day_open, day_high, day_low,
          previous_close, change, pct_change
      FROM raw_stock_quotes
      ORDER BY symbol, quote_ts DESC
    """
)

# Downsample to one point per minute. 15-second polling over 24 hours is
# 5,760 rows per symbol; a browser cannot draw that, and it carries no more
# information than the per-minute closes.
HISTORY_SQL = text(
    """
    SELECT DISTINCT ON (symbol, date_trunc('minute', quote_ts))
          symbol,
          date_trunc('minute', quote_ts) AS minute,
          price
      FROM raw_stock_quotes
    WHERE quote_ts >= now() - make_interval(hours => :hours)
    ORDER BY symbol, date_trunc('minute', quote_ts), quote_ts DESC
    """
)

POLLS_SQL = text(
    """
    SELECT poll_id, started_at, finished_at, market_open, session,
          requests_made, rows_inserted, throttled_seconds, retries,
          breaker_state, status, error_message
      FROM poll_runs
    ORDER BY poll_id DESC
    LIMIT 50
    """
)


# Streamlit re-runs the script on every interaction, so queries are cached.
# The leading underscore keeps the unhashable engine out of the cache key.
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_latest(_engine):
    return pd.read_sql(LATEST_SQL, _engine)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_history(_engine, hours):
    return pd.read_sql(HISTORY_SQL, _engine, params={"hours": hours})


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_polls(_engine):
    return pd.read_sql(POLLS_SQL, _engine)


def to_float(frame, columns):
    """NUMERIC arrives from psycopg2 as Decimal, which pandas holds as object.

    Arithmetic works on Decimal but .mean() and every chart does not, so cast
    at the point of calculation. Storage stays exact; only the display is float.
    """
    out = frame.copy()
    for column in columns:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def index_to_100(pivot):
    """Rebase every series to 100 at its first observation.

    The symbols sit at very different prices, so plotting raw values squashes
    the cheaper ones flat. Indexing makes the shapes comparable.
    """
    first = pivot.apply(lambda s: s.dropna().iloc[0] if s.notna().any() else pd.NA)
    return pivot.divide(first, axis=1) * 100


def render_market_banner(polls):
    if polls.empty:
        st.info("No polls recorded yet.")
        return

    poll = polls.iloc[0]

    if poll["status"] == "failed":
        st.error(f"Last poll failed: {poll['error_message']}")
    if poll["breaker_state"] == "tripped":
        st.error("Circuit breaker is tripped — ingest is not calling the API.")

    session = poll["session"]

    if poll["market_open"]:
        st.success(f"Market open — {session or 'regular'} session.")
    elif session in ("pre-market", "post-market"):
        st.info(f"Regular session closed — {session} trading is live.")
    else:
        st.warning(
            "Market closed. Prices are frozen at the last trade, so no new rows "
            "are stored and the chart will not move until it reopens."
        )


def render_tiles(latest):
    columns = st.columns(len(latest))

    for column, (_, row) in zip(columns, latest.iterrows()):
        price = row["price"]
        pct = row["pct_change"]
        column.metric(
            label=row["symbol"],
            value="—" if pd.isna(price) else f"${price:,.2f}",
            delta=None if pd.isna(pct) else f"{pct:+.2f}%",
        )

def render_polls(polls):
    if polls.empty:
        return

    recent = polls.head(20)
    succeeded = int((recent["status"] == "succeeded").sum())
    throttled = pd.to_numeric(recent["throttled_seconds"], errors="coerce").sum()
    retries = int(pd.to_numeric(recent["retries"], errors="coerce").fillna(0).sum())

    with st.expander(
        f"Ingest health — last {len(recent)} polls: {succeeded} succeeded, "
        f"{retries} retries, {throttled:.1f}s throttled"
    ):
        st.caption(
            "`throttled_seconds` is how long the token bucket held ingest back. "
            "`breaker_state` is healthy, tripped, or testing."
        )
        st.dataframe(recent, use_container_width=True, hide_index=True)


engine = get_destination_engine()

st.title("Live stocks")
st.caption(
    f"Polled from the Finnhub API by the ingest container. Refreshes every {REFRESH}."
)

try:
    engine.connect().close()
except Exception as error:
    st.error(f"Cannot reach destination_postgres — {error}")
    st.stop()

if not table_exists(engine, "raw_stock_quotes"):
    st.warning("`raw_stock_quotes` does not exist yet — start the `ingest` service.")
    st.stop()


# Only this block re-runs on the timer, so the rest of the page does not flicker.
@st.fragment(run_every=REFRESH)
def live():
    latest = to_float(
        load_latest(engine),
        [
            "price",
            "day_open",
            "day_high",
            "day_low",
            "previous_close",
            "change",
            "pct_change",
        ],
    )
    polls = load_polls(engine) if table_exists(engine, "poll_runs") else pd.DataFrame()

    render_market_banner(polls)

    if latest.empty:
        st.info("No quotes stored yet. The first poll takes a few seconds.")
        return

    render_tiles(latest)

    with st.expander("Latest quote detail"):
        st.dataframe(latest, use_container_width=True, hide_index=True)

    render_polls(polls)


live()
