"""Every read the pages make, as DataFrames.

The SQL itself stays in queries.py. This module only runs it, and answers
with an empty frame when a table has not been created yet - so a page never
has to ask whether a service has started before it can draw.
"""

import os

import pandas as pd
import streamlit as st

from db import table_exists
from queries import (
    CANDLE_STATUS_SQL,
    CANDLES_SQL,
    LATEST_SQL,
    ROLLUP_RUNS_SQL,
    SESSIONS_SQL,
    STORAGE_SQL,
)

# The widest window the chart offers, and the one the cache holds. Narrower
# ranges are cut from it in pandas rather than queried again.
HISTORY_HOURS = int(os.environ.get("HISTORY_HOURS", "24"))
HISTORY_CACHE_TTL = 30

PRICE_COLUMNS = ["price", "volume", "day_open", "day_high", "day_low"]
CANDLE_COLUMNS = ["open", "high", "low", "close"]


def to_float(frame, columns):
    """NUMERIC arrives as Decimal, which charts and .mean() cannot handle."""
    out = frame.copy()
    for column in columns:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def _read_if_exists(engine, table, sql):
    if not table_exists(engine, table):
        return pd.DataFrame()
    return pd.read_sql(sql, engine)


def latest(engine):
    return to_float(_read_if_exists(engine, "raw_trades", LATEST_SQL), PRICE_COLUMNS)


def sessions(engine):
    return _read_if_exists(engine, "stream_sessions", SESSIONS_SQL)


def rollup_runs(engine):
    return _read_if_exists(engine, "rollup_runs", ROLLUP_RUNS_SQL)


def storage(engine):
    return _read_if_exists(engine, "raw_trades", STORAGE_SQL)


def candle_status(engine):
    return _read_if_exists(engine, "candles", CANDLE_STATUS_SQL)


def newest(frame):
    """The first row - every query above sorts newest first - or None."""
    return None if frame.empty else frame.iloc[0]


# The only query on the page that reads more than a handful of rows, and the
# only one that is cached. The live panels must not serve stale rows.
@st.cache_data(ttl=HISTORY_CACHE_TTL, show_spinner=False)
def candles(_engine):
    if not table_exists(_engine, "candles"):
        return pd.DataFrame()

    frame = pd.read_sql(CANDLES_SQL, _engine, params={"hours": HISTORY_HOURS})
    return to_float(frame, CANDLE_COLUMNS)
