# elt

A small ELT pipeline that pulls a text-classification dataset from the Hugging Face
Datasets API, cleans and splits it into a ready-to-train dataset, and serves the
result on a Streamlit dashboard. Everything runs as three Docker containers plus a
Postgres database, wired together with Docker Compose.

```
Hugging Face Datasets API
          │
          ▼
   ┌─────────────┐      ┌──────────────┐      ┌────────────────┐
   │   ingest    │ ───▶ │  destination │ ───▶ │   transform     │
   │ (Python)    │      │  _postgres   │      │   (pandas)      │
   └─────────────┘      └──────┬───────┘      └────────┬────────┘
                                │                        │
                                │        writes back     │
                                └────────────◀───────────┘
                                │
                                ▼
                        ┌──────────────┐
                        │  dashboard   │
                        │ (Streamlit)  │
                        └──────────────┘
```

`ingest` and `transform` are one-shot jobs (they run once and exit); `dashboard`
stays up and reads whatever is currently in the database.

## Services

### `ingest/`

Downloads rows from the [Hugging Face Datasets Server API](https://datasets-server.huggingface.co)
and lands them in Postgres, unmodified.

- `config.py` — reads and validates settings from environment variables (dataset
  name, split, page size, sampling strategy, timeout/retry settings). Defaults to
  `fancyzhx/ag_news`.
- `hf_client.py` — a small HTTP client for the API's `/splits` and `/rows`
  endpoints. Retries on `429`/`5xx` with exponential backoff; anything else
  (`401`/`404`/`422`) fails immediately since a retry can't fix it.
- `sampling.py` — decides which page `offset`s to fetch. Two strategies:
  - `sequential` — the first N rows, in order.
  - `strided` (default) — pages spread evenly across the whole dataset, for a
    more representative sample when you're not ingesting everything.
- `writer.py` — upserts fetched rows into `raw_dataset_rows`, using
  `INSERT ... ON CONFLICT DO NOTHING` so re-running ingest never creates
  duplicates.
- `runs.py` — logs every run (start time, end time, rows fetched/inserted,
  success or failure) to `ingestion_runs`, so failures are visible without
  reading container logs.
- `db.py` / `schema.sql` — connects to Postgres and creates the two tables
  above if they don't exist yet.
- `main.py` — orchestrates the above: check the split exists → plan offsets →
  fetch pages → upsert each page in its own transaction → record the run.

### `transform/`

Reads `raw_dataset_rows`, turns it into a clean, deduplicated, split dataset, and
writes the result back. Pure pandas, no Spark/dbt — the dataset is small enough
that a single container handles it comfortably.

- `clean.py` — repairs known encoding issues (e.g. AG News drops the `&` off
  HTML entities), strips HTML tags, unescapes entities, Unicode-normalizes, and
  collapses whitespace. Adds `char_count` / `word_count` columns.
- `dedup.py` — hashes each cleaned text (`sha256`) to make a stable
  `example_id`, then keeps only the first occurrence of each hash.
- `split.py` — assigns each row to `train` / `validation` / `test`. The split is
  **deterministic**: it hashes `seed:example_id` into a number in `[0, 1)` and
  buckets on that, computed *within each label* so class proportions are
  preserved across splits. Re-running transform with the same seed always
  produces the same split.
- `checks.py` — data-quality gate that runs before anything is written:
  no duplicate examples across splits, no empty text, every class present
  above a minimum share in every split, and split sizes within tolerance of
  the configured ratios. If any check fails, nothing is written — the previous
  good tables are left untouched.
- `db.py` — reads/writes whole tables via pandas (`read_sql` / `to_sql`).
- `main.py` — orchestrates: read raw rows → clean → filter by word count →
  hash → dedup → split → quality-check → write `dataset_examples` and
  `dataset_version` (one row describing this build: row counts, split sizes,
  a content fingerprint, and the settings used to build it).

### `dashboard/`

A read-only Streamlit app for inspecting the result: headline counts, class
balance per split, a text-length histogram, a searchable/filterable browser
over `dataset_examples`, and raw tables for debugging (`ingestion_runs`,
`raw_dataset_rows`). Queries are cached for 60 seconds so the UI stays snappy.

## Data model

All tables live in one Postgres database (`destination_db`):

| Table | Written by | Purpose |
|---|---|---|
| `raw_dataset_rows` | ingest | Untouched rows from Hugging Face. Primary key is `(dataset, config, split, row_idx)` — the natural key of a HF row, which is what makes ingest safe to re-run. |
| `ingestion_runs` | ingest | One row per ingest run: status, timing, row counts, error message if it failed. |
| `dataset_examples` | transform | The cleaned, deduplicated, split dataset — `example_id`, `text_clean`, `label`, `label_name`, `char_count`, `word_count`, `split`, `source_row_idx`. Rebuilt (replaced) on every transform run. |
| `dataset_version` | transform | One row per transform run: a fingerprint of the example set, row/split counts, and the parameters used to build it. |

## Running it

```bash
cp .env.example .env   # fill in a Postgres password
docker compose up --build
```

This starts `destination_postgres`, then runs `ingest` to completion, then
`transform` to completion (each waits on the previous step via
`depends_on: condition: service_completed_successfully`), then brings up
`dashboard` at **http://localhost:8501**. Postgres itself is reachable at
`localhost:5434` if you want to poke at it directly.

To pull in new data or rebuild the dataset, just re-run the relevant service:

```bash
docker compose run --rm ingest      # fetch more/different rows
docker compose run --rm transform   # rebuild dataset_examples from raw data
```

## Configuration

All settings are environment variables, loaded from `.env` (see `.env.example`).

**ingest** (`ingest/config.py`)

| Variable | Default | Meaning |
|---|---|---|
| `HF_DATASET` | `fancyzhx/ag_news` | Hugging Face dataset repo |
| `HF_CONFIG` | `default` | Dataset config name |
| `HF_SPLIT` | `train` | Which split to pull |
| `HF_TEXT_COLUMN` / `HF_LABEL_COLUMN` | `text` / `label` | Column names in the source dataset |
| `INGEST_TARGET_ROWS` | `2000` | How many rows to fetch |
| `INGEST_PAGE_SIZE` | `100` | Rows per API call (API caps this at 100) |
| `INGEST_SAMPLING` | `strided` | `strided` or `sequential` |
| `HF_TIMEOUT_SECONDS` / `HF_MAX_RETRIES` | `30` / `5` | HTTP resilience settings |

**transform** (env vars read directly in `transform/main.py`)

| Variable | Default | Meaning |
|---|---|---|
| `SPLIT_SEED` | `42` | Seed for the deterministic train/val/test split |
| `TRAIN_RATIO` / `VAL_RATIO` | `0.8` / `0.1` | Split proportions (test = remainder) |
| `MIN_WORD_COUNT` / `MAX_WORD_COUNT` | `3` / `5000` | Row length filter |
| `MIN_CLASS_SHARE` | `0.10` | Data-quality floor: minimum share any class can have in any split |

**shared Postgres connection** (`DESTINATION_POSTGRES_*`, `SOURCE_POSTGRES_PASSWORD`)

`docker-compose.yaml` sets one password in `.env` (`POSTGRES_PASSWORD`) and
forwards it to every service as `DESTINATION_POSTGRES_PASSWORD`, so there's
only one secret to manage even though several services reference it under
different variable names.

## Project layout

```
ingest/         one-shot job: Hugging Face API → raw_dataset_rows
transform/      one-shot job: raw_dataset_rows → dataset_examples
dashboard/      long-running Streamlit app reading from Postgres
docker-compose.yaml   wires the three services + Postgres together
.env.example    template for the one secret (Postgres password)
```

Each service is an independent Python project with its own `Dockerfile` and
`requirements.txt` — there's no shared package between them, so they can be
built, tested, and versioned separately.
