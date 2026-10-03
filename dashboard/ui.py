"""What every page shares: settings, connections, messages and the look.

The pages under views/ each import this rather than each other, so any one
page can be read on its own.
"""

import html
import os
import re

import streamlit as st

import auth
from db import get_destination_engine
from status import ERROR, IDLE, OK, WARN

# Inside the compose network the service name resolves.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "10"))
STALE_AFTER_SECONDS = float(os.environ.get("STALE_AFTER_SECONDS", "90"))
CANDLE_LAG_GRACE_SECONDS = 300

# st.rerun() restarts the script, so anything written with st.success or
# st.error just before it is thrown away. The outcome goes here instead and
# is drawn on the next run, once.
FEEDBACK_KEY = "feedback"
SESSION_KEYS = ("token", "role", "email")

# Green and red mean up and down, and nothing else on the page.
UP_COLOR = "#16A34A"
DOWN_COLOR = "#DC2626"
MUTED_COLOR = "#64748B"

LEVEL_COLORS = {
    OK: UP_COLOR,
    WARN: "#D97706",
    ERROR: DOWN_COLOR,
    IDLE: MUTED_COLOR,
}

# config.toml in 1.37 only sets colours and the font. Corners, the status
# pill and the pipeline flow have no theme key, so they are styled here.
# The data-testid selectors are Streamlit's own; if a release renames one,
# that element just falls back to the default look.
STYLES = """
<style>
.block-container { padding-top: 2.5rem; max-width: 1200px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
[data-testid="stMetricValue"] { font-weight: 600; }
.pill {
    display: inline-flex; align-items: center; gap: 0.5rem;
    padding: 0.3rem 0.8rem; border-radius: 999px;
    background: #F3F5F9; font-size: 0.9rem; margin-bottom: 0.25rem;
}
.dot {
    display: inline-block; flex: none;
    width: 0.6rem; height: 0.6rem; border-radius: 50%;
}
.pill .label { font-weight: 600; }
.pill .detail { color: #475569; }
.flow { display: flex; flex-wrap: wrap; align-items: stretch; gap: 0.4rem; }
.flow .node {
    flex: 1 1 8rem; padding: 0.7rem 0.9rem; border-radius: 12px;
    border: 1px solid #E2E8F0; background: #FFFFFF;
}
.flow .node .name { font-weight: 600; }
.flow .node .what { color: #64748B; font-size: 0.8rem; }
.flow .arrow { align-self: center; color: #94A3B8; font-size: 1.2rem; }
</style>
"""

INLINE_CODE = re.compile(r"`([^`]+)`")


@st.cache_resource
def engine():
    """One engine per server process. Built per rerun, every page switch would
    open a fresh connection pool and leave the old one for the collector."""
    return get_destination_engine()


@st.cache_resource
def api_session():
    return auth.build_session()


def apply_styles():
    st.markdown(STYLES, unsafe_allow_html=True)


def to_html(text):
    """Escaped first: the text can carry an error_message from the database,
    and it is about to go into the page as raw HTML. Backticks then become
    <code>, so `stream` reads the same here as it does in markdown."""
    return INLINE_CODE.sub(r"<code>\1</code>", html.escape(text))


def dot(level):
    return f'<span class="dot" style="background:{LEVEL_COLORS[level]}"></span>'


def status_pill(state):
    st.markdown(
        f'<div class="pill">{dot(state.level)}'
        f'<span class="label">{html.escape(state.label)}</span>'
        f'<span class="detail">{to_html(state.detail)}</span></div>',
        unsafe_allow_html=True,
    )


def is_admin():
    return st.session_state.get("role") == "admin"


def sign_out():
    for key in SESSION_KEYS:
        st.session_state.pop(key, None)


def remember_feedback(kind, message):
    st.session_state[FEEDBACK_KEY] = (kind, message)


def render_feedback():
    """Draw whatever the last action left behind, then forget it.

    Called before the login gate so a message survives being signed out - an
    expired session would otherwise bounce someone to the form with no
    explanation at all. Good news is a toast, which fades on its own; errors
    stay on the page until the next action, so they cannot be missed.
    """
    remembered = st.session_state.pop(FEEDBACK_KEY, None)

    if remembered is None:
        return

    kind, message = remembered

    if kind == "success":
        st.toast(message, icon="✅")
    elif kind == "info":
        st.toast(message, icon="ℹ️")
    else:
        st.error(message)


def end_dead_session(error):
    """401 from the api: the session is gone, so there is nothing to stay on."""
    remember_feedback("error", f"{error} You have been signed out.")
    sign_out()
    st.rerun()
