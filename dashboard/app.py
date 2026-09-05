import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import get_destination_engine, table_exists
from queries import (
    CANDLE_STATUS_SQL,
    CANDLES_SQL,
    LATEST_SQL,
    ROLLUP_RUNS_SQL,
    SESSIONS_SQL,
    STORAGE_SQL,
)

st.set_page_config(page_title="Live trades", page_icon="📈", layout="wide")

REFRESH = "1s"
CANDLE_REFRESH = "30s"
HISTORY_HOURS = int(os.environ.get("HISTORY_HOURS", "24"))
STALE_AFTER_SECONDS = float(os.environ.get("STALE_AFTER_SECONDS", "90"))
HISTORY_CACHE_TTL = 30
CANDLE_LAG_GRACE_SECONDS = 300

# Green when close >= open, red when it fell. The rollup writes one row per
# minute, so one candle is one minute.
CANDLE_UP_COLOR = "#26a69a"
CANDLE_DOWN_COLOR = "#ef5350"
CANDLE_CHART_HEIGHT = 320
MINUTE_MILLISECONDS = 60_000


def load_latest(engine):
    return pd.read_sql(LATEST_SQL, engine)


def load_sessions(engine):
    return pd.read_sql(SESSIONS_SQL, engine)


def load_storage(engine):
    return pd.read_sql(STORAGE_SQL, engine)


def load_rollup_runs(engine):
    return pd.read_sql(ROLLUP_RUNS_SQL, engine)


def load_candle_status(engine):
    return pd.read_sql(CANDLE_STATUS_SQL, engine)


# The only query on the page that reads more than a handful of rows, and the
# only one that is cached. The live panels must not serve stale rows.
@st.cache_data(ttl=HISTORY_CACHE_TTL, show_spinner=False)
def load_candles(_engine, hours):
    return pd.read_sql(CANDLES_SQL, _engine, params={"hours": hours})


def to_float(frame, columns):
    """NUMERIC arrives as Decimal, which charts and .mean() cannot handle."""
    out = frame.copy()
    for column in columns:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def seconds_since(value):
    if value is None or pd.isna(value):
        return None
    return (pd.Timestamp.now(tz="UTC") - pd.Timestamp(value)).total_seconds()


def format_age(seconds):
    if seconds is None:
        return "never"
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    return f"{seconds / 3600:.1f}h ago"


def render_banner(session):
    """Separates 'quiet market' from 'dead socket' - the point of the heartbeat."""
    if session is None:
        st.info("No stream session recorded yet. Start the `stream` service.")
        return

    if session["status"] == "failed" and session["error_message"]:
        st.error(f"Stream failed: {session['error_message']}")

    message_age = seconds_since(session["last_message_at"])
    trade_age = seconds_since(session["last_trade_at"])

    if message_age is None:
        st.warning("Socket opened, but Finnhub has not sent anything yet.")
        return

    if message_age > STALE_AFTER_SECONDS:
        st.error(
            f"Socket looks stale - last message {format_age(message_age)}. "
            "Check the `stream` container logs."
        )
        return

    market = session["market_session"]

    if session["market_open"]:
        st.success(
            f"Live - market open ({market or 'regular'}). "
            f"Last trade {format_age(trade_age)}."
        )
    elif market in ("pre-market", "post-market"):
        st.info(
            f"Live - regular session closed, {market} trading. "
            f"Last trade {format_age(trade_age)}."
        )
    else:
        st.warning(
            f"Connected and healthy, but the market is closed. "
            f"Last message {format_age(message_age)}, "
            f"last trade {format_age(trade_age)}. The charts will not move."
        )


def render_tiles(latest):
    columns = st.columns(len(latest))

    for column, (_, row) in zip(columns, latest.iterrows(), strict=True):
        price = row["price"]
        day_open = row["day_open"]

        delta = None
        if not pd.isna(price) and not pd.isna(day_open) and day_open:
            delta = f"{(price / day_open - 1) * 100:+.2f}%"

        column.metric(
            label=row["symbol"],
            value="-" if pd.isna(price) else f"${price:,.2f}",
            delta=delta,
        )


def missing_minutes(times):
    """Minutes in the window that have no candle - closed market, or a gap.

    Plotly draws a date axis to scale. Left alone, the overnight gap eats most
    of a 24h chart and squashes the real candles into a sliver, so these get
    cut out of the axis instead.
    """
    present = pd.DatetimeIndex(times)
    whole_window = pd.date_range(present.min(), present.max(), freq="1min")
    return whole_window.difference(present)


def build_candle_figure(symbol, candles):
    """One candle per minute: body spans open to close, wick spans low to high."""
    figure = go.Figure(
        go.Candlestick(
            x=candles["at"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name=symbol,
            increasing_line_color=CANDLE_UP_COLOR,
            decreasing_line_color=CANDLE_DOWN_COLOR,
        )
    )
    figure.update_xaxes(
        rangebreaks=[
            {
                "values": missing_minutes(candles["at"]),
                "dvalue": MINUTE_MILLISECONDS,
            }
        ],
        # The slider is a second copy of the chart under the chart. With one
        # figure per symbol that is a lot of vertical space for little gain.
        rangeslider_visible=False,
    )
    figure.update_yaxes(title_text=None, tickprefix="$")
    figure.update_layout(
        title=symbol,
        height=CANDLE_CHART_HEIGHT,
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        showlegend=False,
    )
    return figure


def render_candle_chart(frame):
    st.subheader("Price history")
    st.caption(
        f"Per-minute candles from the `candles` table, last {HISTORY_HOURS}h. "
        "Each candle is one minute - the body runs open to close, the thin "
        "wick runs low to high. Green closed up, red closed down. Minutes with "
        "no trades are cut out of the axis."
    )

    if frame.empty:
        st.info("No candles yet - the `rollup` service builds them once a minute.")
        return

    candles = to_float(frame, ["open", "high", "low", "close"])

    # One figure per symbol. Candles sit at real prices, so several symbols on
    # shared axes would overlap into mush.
    for symbol in sorted(candles["symbol"].unique()):
        for_symbol = candles[candles["symbol"] == symbol].sort_values("at")
        st.plotly_chart(
            build_candle_figure(symbol, for_symbol),
            use_container_width=True,
            key=f"candles-{symbol}",
        )


def render_health(sessions, storage):
    if sessions.empty:
        return

    current = sessions.iloc[0]
    received = int(current["trades_received"] or 0)
    written = int(current["rows_written"] or 0)
    on_disk = storage.iloc[0]["on_disk"] if not storage.empty else "unknown"

    with st.expander(
        f"Stream health - {len(sessions)} sessions, "
        f"{received:,} trades received, {written:,} rows written, {on_disk} on disk"
    ):
        st.caption(
            "`trades_received` counts what came off the socket, `rows_written` "
            "what reached Postgres. A widening gap means the writer is behind. "
            "`reconnects` is how many times the socket had to come back."
        )
        st.dataframe(sessions, use_container_width=True, hide_index=True)


def render_rollup_health(runs, status, last_trade_at):
    if runs.empty:
        st.info("No rollup run recorded yet. Start the `rollup` service.")
        return

    current = runs.iloc[0]

    if current["status"] == "failed" and current["error_message"]:
        st.error(f"Rollup failed: {current['error_message']}")

    newest = None if status.empty else status.iloc[0]["newest_minute"]
    approx = 0 if status.empty else (status.iloc[0]["approx_candles"] or 0)

    candle_age = seconds_since(newest)
    trade_age = seconds_since(last_trade_at)

    # Stale candles only mean a fault if trades are actually arriving.
    # Overnight there are no new trades AND no new candles, which is correct,
    # and an alarm that fires every night is one nobody reads.
    trades_flowing = trade_age is not None and trade_age < CANDLE_LAG_GRACE_SECONDS
    candles_behind = candle_age is None or candle_age > CANDLE_LAG_GRACE_SECONDS

    if trades_flowing and candles_behind:
        st.warning(
            f"Trades are arriving ({format_age(trade_age)}) but the newest "
            f"candle is {format_age(candle_age)}. Check the `rollup` container."
        )

    with st.expander(
        f"Rollup health - newest candle {format_age(candle_age)}, "
        f"~{int(approx):,} candles stored"
    ):
        st.caption(
            "`trades_read` is how many raw trades the window pulled, "
            "`minutes_written` how many candles it wrote. The same minutes get "
            "rewritten every run on purpose - that is how late trades correct "
            "themselves."
        )
        st.dataframe(runs, use_container_width=True, hide_index=True)


engine = get_destination_engine()

st.title("Live trades")
st.caption(
    "Streamed from the Finnhub websocket by the `stream` container, "
    f"rolled up into minute candles by `rollup`. Prices refresh every {REFRESH}, "
    f"the chart every {CANDLE_REFRESH}."
)

try:
    engine.connect().close()
except Exception as error:
    st.error(f"Cannot reach destination_postgres - {error}")
    st.stop()

if not table_exists(engine, "raw_trades"):
    st.warning("`raw_trades` does not exist yet - start the `stream` service.")
    st.stop()


# Only this block re-runs on the timer, so the page does not flicker.
@st.fragment(run_every=REFRESH)
def live():
    sessions = (
        load_sessions(engine)
        if table_exists(engine, "stream_sessions")
        else pd.DataFrame()
    )
    render_banner(None if sessions.empty else sessions.iloc[0])

    latest = to_float(
        load_latest(engine),
        ["price", "volume", "day_open", "day_high", "day_low"],
    )

    if latest.empty:
        st.info("No trades stored yet. Nothing arrives while the market is closed.")
        render_health(sessions, load_storage(engine))
        return

    render_tiles(latest)

    with st.expander("Latest trade detail"):
        st.dataframe(latest, use_container_width=True, hide_index=True)

    render_health(sessions, load_storage(engine))


# A separate fragment on a slower timer. The price tiles want 1s; redrawing a
# 24-hour chart that only changes once a minute at that rate is pure waste,
# and it visibly flickers.
@st.fragment(run_every=CANDLE_REFRESH)
def history():
    if not table_exists(engine, "candles"):
        st.info("`candles` does not exist yet - start the `rollup` service.")
        return

    render_candle_chart(load_candles(engine, HISTORY_HOURS))

    sessions = (
        load_sessions(engine)
        if table_exists(engine, "stream_sessions")
        else pd.DataFrame()
    )
    last_trade_at = None if sessions.empty else sessions.iloc[0]["last_trade_at"]

    runs = (
        load_rollup_runs(engine)
        if table_exists(engine, "rollup_runs")
        else pd.DataFrame()
    )
    render_rollup_health(runs, load_candle_status(engine), last_trade_at)


live()
history()
