import pandas as pd
import streamlit as st

from db import get_destination_engine, read_table, table_exists

st.set_page_config(page_title="Training dataset", page_icon="📊", layout="wide")

SPLIT_ORDER = ("train", "validation", "test")


# streamlit re-runs the whole script on every interaction, so the queries are
# cached. `_engine` is excluded from the cache key (it is unhashable); the real
# key is db_label + table_name.
@st.cache_data(ttl=60, show_spinner=False)
def load(_engine, db_label, table_name):
    return read_table(_engine, table_name)


engine = get_destination_engine()

st.title("Training dataset")
st.caption(
    "Built from the Hugging Face Datasets API by the ingest and transform containers."
)

st.sidebar.header("Connection")
try:
    engine.connect().close()
    st.sidebar.success("destination_postgres — connected")
except Exception as error:
    st.sidebar.error(f"destination_postgres — {error}")
    st.stop()

if not table_exists(engine, "dataset_examples"):
    st.warning("`dataset_examples` does not exist yet — run `ingest`, then `transform`.")
    st.stop()

examples = load(engine, "destination", "dataset_examples")

# --- headline numbers -------------------------------------------------------
counts = examples["split"].value_counts()

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Examples", f"{len(examples):,}")
col2.metric("Train", f"{counts.get('train', 0):,}")
col3.metric("Validation", f"{counts.get('validation', 0):,}")
col4.metric("Test", f"{counts.get('test', 0):,}")
col5.metric("Classes", int(examples["label_name"].nunique()))

if table_exists(engine, "dataset_version"):
    version = load(engine, "destination", "dataset_version")
    if not version.empty:
        row = version.iloc[0]
        st.caption(
            f"version `{row['version_id']}` · {row['dataset']} / {row['source_split']} · "
            f"{row['n_raw_rows']:,} raw rows in · built {row['built_at']}"
        )

tab_balance, tab_browse, tab_raw = st.tabs(
    ["Class balance", "Browse examples", "Raw + ingest runs"]
)

# --- class balance ----------------------------------------------------------
with tab_balance:
    st.subheader("Examples per class and split")
    # This replaces a stored distribution table: it is a GROUP BY, so it is
    # cheaper to compute on read than to keep in sync on write.
    pivot = pd.crosstab(examples["label_name"], examples["split"])
    pivot = pivot[[name for name in SPLIT_ORDER if name in pivot.columns]]
    st.bar_chart(pivot)
    st.dataframe(pivot, use_container_width=True)

    st.subheader("Text length (words)")
    buckets = pd.cut(examples["word_count"], bins=20)
    histogram = examples.groupby(buckets, observed=True).size()
    histogram.index = [f"{int(b.left)}-{int(b.right)}" for b in histogram.index]
    st.bar_chart(histogram)

# --- browse -----------------------------------------------------------------
with tab_browse:
    left, right = st.columns(2)
    split_choice = left.selectbox(
        "Split", ["all", *[s for s in SPLIT_ORDER if s in set(examples["split"])]]
    )
    label_choice = right.selectbox(
        "Class", ["all", *sorted(examples["label_name"].dropna().unique())]
    )

    view = examples
    if split_choice != "all":
        view = view[view["split"] == split_choice]
    if label_choice != "all":
        view = view[view["label_name"] == label_choice]

    st.caption(f"{len(view):,} examples — showing the first 200")
    st.dataframe(
        view[["text_clean", "label_name", "split", "word_count"]].head(200),
        use_container_width=True,
        hide_index=True,
    )

# --- raw --------------------------------------------------------------------
with tab_raw:
    for table_name in ("ingestion_runs", "raw_dataset_rows"):
        if not table_exists(engine, table_name):
            st.info(f"`{table_name}` does not exist yet.")
            continue
        frame = load(engine, "destination", table_name)
        with st.expander(f"{table_name} — {len(frame):,} rows"):
            st.dataframe(frame.head(200), use_container_width=True, hide_index=True)
