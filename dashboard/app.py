import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auth
from db import get_destination_engine, table_exists
from queries import (
    ALERTS_SQL,
    CANDLE_STATUS_SQL,
    CANDLES_SQL,
    INSERT_ALERT_SQL,
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
# Inside the compose network the service name resolves; there is no
# dashboard/config.py and two variables do not justify inventing one.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "10"))

# st.rerun() restarts the script, so anything written with st.success or
# st.error just before it is thrown away. The outcome goes here instead and
# is drawn on the next run, once.
FEEDBACK_KEY = "feedback"
HISTORY_CACHE_TTL = 30
CANDLE_LAG_GRACE_SECONDS = 300

# Green when close >= open, red when it fell. The rollup writes one row per
# minute, so one candle is one minute.
CANDLE_UP_COLOR = "#26a69a"
CANDLE_DOWN_COLOR = "#ef5350"
CANDLE_CHART_HEIGHT = 320
MINUTE_MILLISECONDS = 60_000

# Matches the CHECK constraint on price_alerts.direction.
ALERT_DIRECTIONS = ("above", "below")
ALERT_MIN_THRESHOLD = 0.01


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


def load_alerts(engine):
    return pd.read_sql(ALERTS_SQL, engine)


def create_alert(engine, symbol, direction, threshold):
    """The only row this page writes. Everything else here is read-only."""
    with engine.begin() as connection:
        connection.execute(
            INSERT_ALERT_SQL,
            {"symbol": symbol, "direction": direction, "threshold": threshold},
        )


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


def alert_status(row):
    """One readable column instead of two raw values to compare by eye."""
    if pd.isna(row["triggered_at"]):
        return "waiting"

    return f"fired at ${row['triggered_price']:,.2f}"


def render_alert_form(engine):
    """Deliberately outside every fragment.

    A form inside a fragment on a timer is redrawn every few seconds, which
    wipes whatever the user is halfway through typing.
    """
    st.subheader("Price alerts")

    if not table_exists(engine, "price_alerts"):
        st.info("`price_alerts` does not exist yet - start the `rollup` service.")
        return

    st.caption(
        "The `rollup` service checks these once a minute against the newest "
        "candle close. An alert fires once, records the price that set it off, "
        "and then stays put."
    )

    with st.form("new-alert", clear_on_submit=True):
        symbol_column, direction_column, price_column = st.columns([2, 1, 1])
        symbol = symbol_column.text_input("Symbol", placeholder="NVDA")
        direction = direction_column.selectbox("When the price is", ALERT_DIRECTIONS)
        threshold = price_column.number_input(
            "this price", min_value=ALERT_MIN_THRESHOLD, value=None, step=1.0
        )
        submitted = st.form_submit_button("Add alert")

    if not submitted:
        return

    # Symbols are stored the way the feed sends them, so match that here -
    # an alert on "nvda" would wait for a price that never arrives.
    wanted = symbol.strip().upper()

    if not wanted:
        st.error("Enter a symbol.")
        return

    if threshold is None:
        st.error("Enter a price to watch for.")
        return

    create_alert(engine, wanted, direction, float(threshold))
    st.success(f"Watching {wanted} for {direction} ${threshold:,.2f}.")


def render_alert_list(engine):
    alerts = load_alerts(engine)

    if alerts.empty:
        st.caption("No alerts yet.")
        return

    shown = to_float(alerts, ["threshold", "triggered_price"])
    shown["status"] = shown.apply(alert_status, axis=1)

    st.dataframe(
        shown[["symbol", "direction", "threshold", "status", "created_at"]],
        use_container_width=True,
        hide_index=True,
    )


@st.cache_resource
def api_session():
    return auth.build_session()


def sign_out():
    for key in ("token", "role", "username"):
        st.session_state.pop(key, None)


def render_login():
    st.subheader("Sign in")

    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if not submitted:
        return

    try:
        credentials = auth.login(
            api_session(), API_BASE_URL, username, password, API_TIMEOUT_SECONDS
        )
    except auth.AuthError as error:
        st.error(str(error))
        return
    except Exception as error:
        # A dead api is not a credentials problem. Saying "wrong password" here
        # would send someone round a loop retyping a correct one.
        st.error(f"Cannot reach the api - {error}")
        return

    # Lower-cased to match what the api stored, so the sidebar shows the name
    # the account actually has.
    st.session_state["token"] = credentials.token
    st.session_state["role"] = credentials.role
    st.session_state["username"] = username.strip().lower()
    st.rerun()


def render_register():
    st.caption(
        "New accounts are always plain users. Only an admin can delete alerts."
    )

    with st.form("register"):
        # max_chars mirrors the api's RegisterRequest, so an over-long entry is
        # refused here rather than coming back as an opaque 422.
        username = st.text_input("Choose a username", max_chars=64)
        password = st.text_input("Choose a password", type="password", max_chars=72)
        submitted = st.form_submit_button("Create account")

    if not submitted:
        return

    if not username.strip() or not password:
        st.error("Enter a username and a password.")
        return

    try:
        created = auth.register(
            api_session(), API_BASE_URL, username, password, API_TIMEOUT_SECONDS
        )
    except Exception as error:
        st.error(f"Cannot reach the api - {error}")
        return

    if created:
        st.success("Account created. Sign in on the other tab.")
    else:
        # Not an error the api treats as a failure of yours - just pick another.
        st.error("That username is already taken.")


def remember_feedback(kind, message):
    st.session_state[FEEDBACK_KEY] = (kind, message)


def render_feedback():
    """Draw whatever the last action left behind, then forget it.

    Called before the login gate so a message survives being signed out - an
    expired session would otherwise bounce someone to the form with no
    explanation at all.
    """
    remembered = st.session_state.pop(FEEDBACK_KEY, None)

    if remembered is None:
        return

    kind, message = remembered

    if kind == "success":
        st.success(message)
    elif kind == "info":
        st.info(message)
    else:
        st.error(message)


def render_sidebar():
    with st.sidebar:
        st.write(
            f"Signed in as **{st.session_state['username']}** "
            f"({st.session_state['role']})"
        )

        if st.button("Log out"):
            sign_out()
            st.rerun()


def render_delete_alert(engine):
    alerts = load_alerts(engine)

    if alerts.empty:
        return

    # Shown to everyone on purpose. Hiding the control from a plain user would
    # be cosmetic: the api re-reads the role from the token on every delete, and
    # that refusal is what actually enforces it. Letting them press it means the
    # rule is demonstrated rather than merely assumed.
    st.caption("Deleting an alert needs an admin account.")

    with st.form("delete-alert", clear_on_submit=True):
        alert_id = st.selectbox(
            "Delete an alert", alerts["alert_id"], format_func=lambda row: f"#{row}"
        )
        submitted = st.form_submit_button("Delete alert")

    if not submitted:
        return

    try:
        removed = auth.delete_alert(
            api_session(),
            API_BASE_URL,
            st.session_state["token"],
            int(alert_id),
            API_TIMEOUT_SECONDS,
        )
    except auth.NotAllowedError as error:
        # Caught before AuthError, because it is a subclass and Python takes the
        # first matching branch. Signed in correctly, just not an admin - so no
        # rerun and no sign out, and the message stays on screen.
        st.error(str(error))
        return
    except auth.AuthError as error:
        # 401: the session itself is dead, so there is nothing to stay on.
        remember_feedback("error", f"{error} You have been signed out.")
        sign_out()
        st.rerun()
    except Exception as error:
        # Covers both a dead api and one that answered with a 5xx, so the
        # wording does not claim to know which.
        st.error(f"Could not delete alert #{alert_id} - {error}")
        return

    if removed:
        remember_feedback("success", f"Alert #{alert_id} deleted.")
    else:
        # Someone else got there first. Ordinary, so not an error.
        remember_feedback("info", f"Alert #{alert_id} was already gone.")

    st.rerun()


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


render_feedback()

if "token" not in st.session_state:
    sign_in_tab, register_tab = st.tabs(["Sign in", "Register"])

    with sign_in_tab:
        render_login()

    with register_tab:
        render_register()

    st.stop()

render_sidebar()


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


# The list gets its own fragment so a fired alert appears on its own, without
# the user having to touch the page. The form above it stays out of any
# fragment - see render_alert_form.
@st.fragment(run_every=CANDLE_REFRESH)
def alerts():
    if not table_exists(engine, "price_alerts"):
        return

    render_alert_list(engine)


live()
history()
render_alert_form(engine)
render_delete_alert(engine)
alerts()
