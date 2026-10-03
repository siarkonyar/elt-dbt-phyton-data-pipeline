"""Alerts: set a price to watch for, see which ones fired, remove old ones.

Every read and write goes through the api, never straight to Postgres.
Run by st.navigation as a script, top to bottom, like app.py itself.
"""

import pandas as pd
import streamlit as st

import auth
import ui

LIST_REFRESH = "30s"

# Matches the CHECK constraint on price_alerts.direction.
ALERT_DIRECTIONS = ("above", "below")
ALERT_MIN_THRESHOLD = 0.01

TABLE_COLUMNS = ["alert_id", "symbol", "condition", "status", "created_at"]
COLUMN_CONFIG = {
    "alert_id": st.column_config.NumberColumn("#", format="#%d", width="small"),
    "email": st.column_config.TextColumn("Owner"),
    "symbol": st.column_config.TextColumn("Symbol"),
    "condition": st.column_config.TextColumn("Condition"),
    "status": st.column_config.TextColumn("Status"),
    "created_at": st.column_config.DatetimeColumn("Created", format="MMM D, HH:mm"),
}


def token():
    return st.session_state["token"]


def fetch_alerts():
    """The api's list as a DataFrame, or None once the problem is on screen.

    The api decides whose alerts come back. Reading price_alerts straight from
    Postgres here would show a plain user everyone's.
    """
    try:
        rows = auth.list_alerts(
            ui.api_session(), ui.API_BASE_URL, token(), ui.API_TIMEOUT_SECONDS
        )
    except auth.AuthError as error:
        ui.end_dead_session(error)
    except Exception as error:
        # Shown in place, so the tiles and charts keep working without the api.
        st.error(f"Cannot load alerts - {error}")
        return None

    return pd.DataFrame(rows)


def condition(row):
    return f"{row['direction'].capitalize()} ${row['threshold']:,.2f}"


def alert_status(row):
    """One readable column instead of two raw values to compare by eye."""
    if pd.isna(row["triggered_at"]):
        return "⏳ Waiting"

    return f"🔔 Fired at ${row['triggered_price']:,.2f}"


def alert_label(row):
    return f"#{row.alert_id} · {row.symbol} {row.direction} ${row.threshold:,.2f}"


def create_alert(symbol, direction, threshold):
    # Symbols are stored the way the feed sends them, so match that here -
    # an alert on "nvda" would wait for a price that never arrives.
    wanted = symbol.strip().upper()

    if not wanted:
        st.error("Enter a symbol.")
        return

    if threshold is None:
        st.error("Enter a price to watch for.")
        return

    try:
        auth.create_alert(
            ui.api_session(),
            ui.API_BASE_URL,
            token(),
            wanted,
            direction,
            float(threshold),
            ui.API_TIMEOUT_SECONDS,
        )
    except auth.AuthError as error:
        ui.end_dead_session(error)
    except Exception as error:
        st.error(f"Could not add the alert - {error}")
        return

    # A rerun rather than an st.success here, so the new alert is in the list
    # straight away instead of on the list's next 30s tick.
    ui.remember_feedback(
        "success", f"Watching {wanted} for {direction} ${threshold:,.2f}."
    )
    st.rerun()


def render_alert_form():
    """Deliberately outside every fragment.

    A form inside a fragment on a timer is redrawn every few seconds, which
    wipes whatever the user is halfway through typing.
    """
    with st.container(border=True):
        st.markdown("**New alert**")

        with st.form("new-alert", clear_on_submit=True, border=False):
            symbol_column, direction_column, price_column = st.columns(3)
            symbol = symbol_column.text_input("Symbol", placeholder="NVDA")
            direction = direction_column.selectbox(
                "When the price is", ALERT_DIRECTIONS
            )
            threshold = price_column.number_input(
                "this price", min_value=ALERT_MIN_THRESHOLD, value=None, step=1.0
            )
            submitted = st.form_submit_button("Add alert", type="primary")

    if submitted:
        create_alert(symbol, direction, threshold)


def delete_alert(alert_id):
    try:
        removed = auth.delete_alert(
            ui.api_session(),
            ui.API_BASE_URL,
            token(),
            int(alert_id),
            ui.API_TIMEOUT_SECONDS,
        )
    except auth.NotAllowedError as error:
        # Caught before AuthError, because it is a subclass and Python takes the
        # first matching branch. Signed in correctly, just not an admin - so no
        # rerun and no sign out, and the message stays on screen.
        st.error(str(error))
        return
    except auth.AuthError as error:
        # 401: the session itself is dead, so there is nothing to stay on.
        ui.end_dead_session(error)
    except Exception as error:
        # Covers both a dead api and one that answered with a 5xx, so the
        # wording does not claim to know which.
        st.error(f"Could not delete alert #{alert_id} - {error}")
        return

    if removed:
        ui.remember_feedback("success", f"Alert #{alert_id} deleted.")
    else:
        # Someone else got there first. Ordinary, so not an error.
        ui.remember_feedback("info", f"Alert #{alert_id} was already gone.")

    st.rerun()


@st.dialog("Delete alert")
def confirm_delete(alert_id, label):
    st.write(f"Delete **{label}**? The stream stops watching for it.")

    cancel_column, delete_column = st.columns(2)

    if cancel_column.button("Cancel", use_container_width=True):
        st.rerun()

    if delete_column.button("Delete", type="primary", use_container_width=True):
        delete_alert(alert_id)


def render_delete_control():
    with st.container(border=True):
        st.markdown("**Remove an alert**")
        alerts = fetch_alerts()

        if alerts is None:
            return

        if alerts.empty:
            st.caption("Nothing to remove yet.")
            return

        labels = {
            row.alert_id: alert_label(row) for row in alerts.itertuples(index=False)
        }
        alert_id = st.selectbox(
            "Alert",
            list(labels),
            format_func=labels.get,
            key="delete-alert-id",
            label_visibility="collapsed",
        )

        # Shown to everyone on purpose. Hiding the control from a plain user would
        # be cosmetic: the api re-reads the role from the token on every delete, and
        # that refusal is what actually enforces it. Letting them press it means the
        # rule is demonstrated rather than merely assumed.
        st.caption("Deleting an alert needs an admin account.")

        if st.button("Delete…", use_container_width=True):
            confirm_delete(alert_id, labels[alert_id])


def describe(alerts):
    return alerts.assign(
        condition=alerts.apply(condition, axis=1),
        status=alerts.apply(alert_status, axis=1),
        # JSON carries times as ISO strings; a real datetime displays properly.
        created_at=pd.to_datetime(alerts["created_at"]),
    )


# The list gets its own fragment so a fired alert appears on its own, without
# the user having to touch the page. The form above it stays out of any
# fragment - see render_alert_form.
@st.fragment(run_every=LIST_REFRESH)
def alert_board():
    alerts = fetch_alerts()

    if alerts is None:
        return

    if alerts.empty:
        st.info("No alerts yet. Add one above and the stream checks every trade.")
        return

    fired = int(alerts["triggered_at"].notna().sum())
    watching_column, fired_column = st.columns(2)

    with watching_column.container(border=True):
        st.metric("Watching", len(alerts) - fired)

    with fired_column.container(border=True):
        st.metric("Fired", fired)

    # An admin sees everyone's alerts, so they need to know whose is whose.
    columns = (
        ["alert_id", "email", *TABLE_COLUMNS[1:]] if ui.is_admin() else TABLE_COLUMNS
    )

    st.dataframe(
        describe(alerts)[columns],
        column_config=COLUMN_CONFIG,
        use_container_width=True,
        hide_index=True,
    )


st.title("Alerts")
st.caption(
    "The `stream` service checks every trade against these as it arrives. "
    "An alert fires once, records the trade that set it off, and then "
    "stays put."
)

create_column, delete_column = st.columns([3, 2])

with create_column:
    render_alert_form()

with delete_column:
    render_delete_control()

alert_board()
