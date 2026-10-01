"""Markets: is the feed alive, what is every symbol doing, and one chart.

Run by st.navigation as a script, top to bottom, like app.py itself.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import status
import ui

PRICE_REFRESH = "1s"
CHART_REFRESH = "30s"

CARDS_PER_ROW = 4
SPARKLINE_POINTS = 120
SPARKLINE_WIDTH = 200
SPARKLINE_HEIGHT = 36
SPARKLINE_PADDING = 2

CHART_HEIGHT = 460
GRID_COLOR = "#EEF2F7"
MINUTE_MILLISECONDS = 60_000
RANGE_HOURS = sorted({1, 6, data.HISTORY_HOURS})

engine = ui.engine()


def percent_change(price, day_open):
    if pd.isna(price) or pd.isna(day_open) or not day_open:
        return None
    return (price / day_open - 1) * 100


def money(value):
    return "-" if pd.isna(value) else f"${value:,.2f}"


def closes_for(candles, symbol):
    if candles.empty:
        return []
    for_symbol = candles[candles["symbol"] == symbol]
    return for_symbol["close"].dropna().tail(SPARKLINE_POINTS).tolist()


def sparkline(values, color):
    """A bare SVG line. Five Plotly figures redrawn every second flicker and
    cost far more than the few hundred characters this needs."""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = SPARKLINE_WIDTH / (len(values) - 1)
    usable = SPARKLINE_HEIGHT - 2 * SPARKLINE_PADDING

    points = " ".join(
        f"{index * step:.1f},"
        f"{SPARKLINE_PADDING + usable - (value - low) / span * usable:.1f}"
        for index, value in enumerate(values)
    )
    return (
        f'<svg viewBox="0 0 {SPARKLINE_WIDTH} {SPARKLINE_HEIGHT}" width="100%" '
        f'height="{SPARKLINE_HEIGHT}" preserveAspectRatio="none">'
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        'stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>'
    )


def render_card(row, closes):
    change = percent_change(row.price, row.day_open)

    with st.container(border=True):
        st.metric(
            label=row.symbol,
            value=money(row.price),
            delta=None if change is None else f"{change:+.2f}%",
        )

        rising = change is None or change >= 0
        if len(closes) > 1:
            color = ui.UP_COLOR if rising else ui.DOWN_COLOR
            st.markdown(sparkline(closes, color), unsafe_allow_html=True)

        trades = 0 if pd.isna(row.trades_today) else int(row.trades_today)
        st.caption(
            f"H {money(row.day_high)} · L {money(row.day_low)} · "
            f"{trades:,} trades today"
        )


def render_cards(latest, candles):
    rows = list(latest.itertuples(index=False))

    for start in range(0, len(rows), CARDS_PER_ROW):
        columns = st.columns(CARDS_PER_ROW)
        batch = rows[start : start + CARDS_PER_ROW]
        for column, row in zip(columns, batch, strict=False):
            with column:
                render_card(row, closes_for(candles, row.symbol))


# Only this block re-runs on the timer, so the page does not flicker.
@st.fragment(run_every=PRICE_REFRESH)
def live_board():
    session = data.newest(data.sessions(engine))
    ui.status_pill(status.stream_status(session, ui.STALE_AFTER_SECONDS))

    latest = data.latest(engine)
    if latest.empty:
        st.info("No trades stored yet. Nothing arrives while the market is closed.")
        return

    render_cards(latest, data.candles(engine))


def missing_minutes(times):
    """Minutes in the window that have no candle - closed market, or a gap.

    Plotly draws a date axis to scale. Left alone, the overnight gap eats most
    of a 24h chart and squashes the real candles into a sliver, so these get
    cut out of the axis instead.
    """
    present = pd.DatetimeIndex(times)
    whole_window = pd.date_range(present.min(), present.max(), freq="1min")
    return whole_window.difference(present)


def build_figure(candles):
    """One candle per minute: body spans open to close, wick spans low to high."""
    figure = go.Figure(
        go.Candlestick(
            x=candles["at"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            increasing_line_color=ui.UP_COLOR,
            increasing_fillcolor=ui.UP_COLOR,
            decreasing_line_color=ui.DOWN_COLOR,
            decreasing_fillcolor=ui.DOWN_COLOR,
        )
    )
    figure.update_xaxes(
        rangebreaks=[
            {"values": missing_minutes(candles["at"]), "dvalue": MINUTE_MILLISECONDS}
        ],
        rangeslider_visible=False,
        showgrid=False,
    )
    # Prices on the right, where trading screens put them, so the newest
    # candle sits right next to its own scale.
    figure.update_yaxes(tickprefix="$", side="right", gridcolor=GRID_COLOR)
    figure.update_layout(
        height=CHART_HEIGHT,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        showlegend=False,
        hovermode="x unified",
    )
    return figure


# A separate fragment on a slower timer. The price tiles want 1s; redrawing a
# 24-hour chart that only changes once a minute at that rate is pure waste,
# and it visibly flickers.
@st.fragment(run_every=CHART_REFRESH)
def chart(symbol, hours):
    candles = data.candles(engine)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
    window = candles[(candles["symbol"] == symbol) & (candles["at"] >= cutoff)]

    if window.empty:
        st.info(f"No {symbol} candles in the last {hours}h.")
        return

    st.plotly_chart(
        build_figure(window.sort_values("at")),
        use_container_width=True,
        key="price-chart",
    )
    st.caption(
        "One candle per minute. The body runs open to close, the wick low to "
        "high; green closed up, red closed down. Minutes with no trades are "
        "cut out of the axis."
    )


def render_history():
    st.subheader("Price history")
    candles = data.candles(engine)

    if candles.empty:
        st.info("No candles yet - the `rollup` service builds them once a minute.")
        return

    # Outside the fragment on purpose: a widget inside a timed fragment gets
    # redrawn by the timer. Changing either one reruns the page once and hands
    # the new choice to the chart.
    picker, ranges = st.columns([1, 2])
    symbol = picker.selectbox(
        "Symbol",
        sorted(candles["symbol"].unique()),
        key="chart-symbol",
        label_visibility="collapsed",
    )
    hours = ranges.radio(
        "Range",
        RANGE_HOURS,
        index=len(RANGE_HOURS) - 1,
        format_func=lambda value: f"{value}h",
        horizontal=True,
        key="chart-hours",
        label_visibility="collapsed",
    )
    chart(symbol, hours)


st.title("Markets")
st.caption(
    "Live US equity trades from the Finnhub websocket, rolled up into "
    "one-minute candles."
)
live_board()
render_history()
