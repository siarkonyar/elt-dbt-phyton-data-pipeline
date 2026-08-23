import streamlit as st

from db import (
    get_destination_engine,
    get_source_engine,
    read_table,
    table_exists,
)

SOURCE_TABLES = ["trainers", "members", "gym_classes", "bookings"]

DESTINATION_TABLES = [
    "stg_trainers",
    "stg_members",
    "stg_gym_classes",
    "stg_bookings",
    "fct_bookings",
    "dim_attendance",
]

st.set_page_config(page_title="GYM dataset transformation", page_icon="🏋️", layout="wide")

#streamlit renders the whole page from scratch on every event that is why we need to cache
@st.cache_data(ttl=60, show_spinner=False)
def load_table(_engine, db_label, table_name):#db_label is for cahcing only. it is like a key
    return read_table(_engine, table_name)

def render_tables(engine, db_label, table_names):
    for table_name in table_names:
        if not table_exists(engine, table_name):
            st.warning(f"`{table_name}` does not exist yet — run the transform.")
            continue

        df = load_table(engine, db_label, table_name)

        with st.expander(f"{table_name} — {len(df)} rows", expanded=False):
            st.dataframe(df, use_container_width=True, hide_index=True)


def render_sidebar(source_engine, destination_engine):
    st.sidebar.header("Connections")

    for label, engine in [
        ("source_postgres", source_engine),
        ("destination_postgres", destination_engine),
    ]:
        try:
            engine.connect().close()
            st.sidebar.success(f"{label} — connected")
        except Exception as error:
            st.sidebar.error(f"{label} — {error}")

st.title("GYM dataa")
st.caption("Raw data on one side, transformed data on the other.")

source_engine = get_source_engine()
destination_engine = get_destination_engine()

render_sidebar(source_engine, destination_engine)

before, after = st.tabs(["Source (before)", "Destination (after)"])

with before:
    st.subheader("source_postgres")
    st.write("The raw gym data, exactly as `init.sql` created it.")
    render_tables(source_engine, "source", SOURCE_TABLES)

with after:
    st.subheader("destination_postgres")
    st.write("What the transform container built: staging tables, then marts.")
    render_tables(destination_engine, "destination", DESTINATION_TABLES)