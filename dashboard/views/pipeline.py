"""Pipeline: every stage between the Finnhub socket and this page, and
whether each one is keeping up.

Run by st.navigation as a script, top to bottom, like app.py itself.
"""

import html

import pandas as pd
import streamlit as st

import data
import status
import ui

HEALTH_REFRESH = "5s"
ARROW = '<div class="arrow">→</div>'

STREAM_NOTE = (
    "`trades_received` counts what came off the socket, `rows_written` "
    "what reached Postgres. A widening gap means the writer is behind. "
    "`reconnects` is how many times the socket had to come back."
)
ROLLUP_NOTE = (
    "`trades_read` is how many raw trades the window pulled, "
    "`minutes_written` how many candles it wrote. The same minutes get "
    "rewritten every run on purpose - that is how late trades correct "
    "themselves."
)

engine = ui.engine()


def field(row, name):
    return None if row is None else row[name]


def count(value):
    if value is None or pd.isna(value):
        return 0
    # reltuples is -1 until Postgres first analyses the table.
    return max(int(value), 0)


def age_of(value):
    return status.format_age(status.seconds_since(value))


def node(level, name, what):
    return (
        f'<div class="node">{ui.dot(level)} '
        f'<span class="name">{html.escape(name)}</span>'
        f'<div class="what">{html.escape(what)}</div></div>'
    )


def render_flow(stream, rollup, session, storage, candles, run):
    raw_rows = count(field(storage, "approx_rows"))
    on_disk = field(storage, "on_disk") or "empty"

    nodes = [
        node(
            stream.level,
            "Finnhub",
            f"last message {age_of(field(session, 'last_message_at'))}",
        ),
        node(
            stream.level,
            "stream",
            f"{count(field(session, 'trades_received')):,} trades received",
        ),
        node(
            status.OK if raw_rows else status.IDLE,
            "raw_trades",
            f"{on_disk} · ~{raw_rows:,} rows",
        ),
        node(rollup.level, "rollup", f"last run {age_of(field(run, 'started_at'))}"),
        node(
            rollup.level,
            "candles",
            f"newest {age_of(field(candles, 'newest_minute'))}",
        ),
        node(status.OK, "dashboard", "you are here"),
    ]
    st.markdown(f'<div class="flow">{ARROW.join(nodes)}</div>', unsafe_allow_html=True)


def render_stream(stream, session):
    st.subheader("Stream")
    ui.status_pill(stream)

    received = count(field(session, "trades_received"))
    written = count(field(session, "rows_written"))

    with st.container(border=True):
        left, right = st.columns(2)
        left.metric("Trades received", f"{received:,}", help=STREAM_NOTE)
        right.metric("Rows written", f"{written:,}", help=STREAM_NOTE)
        left.metric("Writer backlog", f"{received - written:,}", help=STREAM_NOTE)
        right.metric("Reconnects", count(field(session, "reconnects")))


def render_rollup(rollup, run, candles):
    st.subheader("Rollup")
    ui.status_pill(rollup)

    with st.container(border=True):
        left, right = st.columns(2)
        left.metric("Candles stored", f"~{count(field(candles, 'approx_candles')):,}")
        right.metric("Newest candle", age_of(field(candles, "newest_minute")))
        left.metric(
            "Trades read", f"{count(field(run, 'trades_read')):,}", help=ROLLUP_NOTE
        )
        right.metric(
            "Minutes written",
            f"{count(field(run, 'minutes_written')):,}",
            help=ROLLUP_NOTE,
        )


def render_tables(sessions, runs):
    with st.expander(f"Stream sessions ({len(sessions)})"):
        st.caption(STREAM_NOTE)
        st.dataframe(sessions, use_container_width=True, hide_index=True)

    with st.expander(f"Rollup runs ({len(runs)})"):
        st.caption(ROLLUP_NOTE)
        st.dataframe(runs, use_container_width=True, hide_index=True)

    with st.expander("Latest trade per symbol"):
        st.dataframe(data.latest(engine), use_container_width=True, hide_index=True)


@st.fragment(run_every=HEALTH_REFRESH)
def health():
    sessions = data.sessions(engine)
    runs = data.rollup_runs(engine)
    session = data.newest(sessions)
    run = data.newest(runs)
    storage = data.newest(data.storage(engine))
    candles = data.newest(data.candle_status(engine))

    stream = status.stream_status(session, ui.STALE_AFTER_SECONDS)
    rollup = status.rollup_status(
        run,
        field(candles, "newest_minute"),
        field(session, "last_trade_at"),
        ui.CANDLE_LAG_GRACE_SECONDS,
    )

    render_flow(stream, rollup, session, storage, candles, run)

    stream_column, rollup_column = st.columns(2)

    with stream_column:
        render_stream(stream, session)

    with rollup_column:
        render_rollup(rollup, run, candles)

    render_tables(sessions, runs)


st.title("Pipeline")
st.caption(
    "How a trade gets from the Finnhub websocket to this page, and whether "
    "every stage is keeping up."
)
health()
