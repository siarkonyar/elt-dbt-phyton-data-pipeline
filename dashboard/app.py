"""Entry point: checks the database, signs people in, then hands over to the
page they picked. The pages themselves live in views/."""

import streamlit as st

import auth
import ui
from db import table_exists

st.set_page_config(page_title="Live trades", page_icon="📈", layout="wide")
ui.apply_styles()

# Paths are relative to this file. The folder is views/, not pages/: Streamlit
# treats a pages/ folder as its older multipage mode and would list every file
# in it a second time.
PAGES = [
    st.Page("views/markets.py", title="Markets", icon="📈", default=True),
    st.Page("views/alerts.py", title="Alerts", icon="🔔"),
    st.Page("views/pipeline.py", title="Pipeline", icon="🛠️"),
]


def render_login():
    with st.form("login", border=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button(
            "Sign in", type="primary", use_container_width=True
        )

    if not submitted:
        return

    try:
        credentials = auth.login(
            ui.api_session(),
            ui.API_BASE_URL,
            username,
            password,
            ui.API_TIMEOUT_SECONDS,
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
    st.caption("New accounts are always plain users. Only an admin can delete alerts.")

    with st.form("register", border=False):
        # max_chars mirrors the api's RegisterRequest, so an over-long entry is
        # refused here rather than coming back as an opaque 422.
        username = st.text_input("Choose a username", max_chars=64)
        password = st.text_input("Choose a password", type="password", max_chars=72)
        submitted = st.form_submit_button(
            "Create account", type="primary", use_container_width=True
        )

    if not submitted:
        return

    if not username.strip() or not password:
        st.error("Enter a username and a password.")
        return

    try:
        created = auth.register(
            ui.api_session(),
            ui.API_BASE_URL,
            username,
            password,
            ui.API_TIMEOUT_SECONDS,
        )
    except Exception as error:
        st.error(f"Cannot reach the api - {error}")
        return

    if created:
        st.success("Account created. Sign in on the other tab.")
    else:
        # Not an error the api treats as a failure of yours - just pick another.
        st.error("That username is already taken.")


def render_sign_in_page():
    _, middle, _ = st.columns([1, 2, 1])

    with middle:
        st.title("📈 Live trades")
        st.caption(
            "Real-time US equity trades, streamed from Finnhub and rolled up "
            "into one-minute candles. Sign in to watch the market and set "
            "price alerts."
        )

        with st.container(border=True):
            sign_in_tab, register_tab = st.tabs(["Sign in", "Register"])

            with sign_in_tab:
                render_login()

            with register_tab:
                render_register()


def render_sidebar():
    with st.sidebar:
        st.divider()
        st.caption("Signed in as")
        st.markdown(f"**{st.session_state['username']}** · {st.session_state['role']}")

        if st.button("Log out", use_container_width=True):
            ui.sign_out()
            st.rerun()


engine = ui.engine()

try:
    engine.connect().close()
except Exception as error:
    st.error(f"Cannot reach destination_postgres - {error}")
    st.stop()

if not table_exists(engine, "raw_trades"):
    st.warning("`raw_trades` does not exist yet - start the `stream` service.")
    st.stop()


ui.render_feedback()

if "token" not in st.session_state:
    render_sign_in_page()
    st.stop()

page = st.navigation(PAGES)
render_sidebar()
page.run()
