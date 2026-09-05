# Candle rollup, testing, and CI — design

**Date:** 2026-08-31
**Branch:** `feat/ci`
**Status:** approved, ready for implementation planning

## Why

The project is called an ELT pipeline but there is no T. The `stream` service
captures Finnhub trades into `raw_trades`, and the dashboard derives everything
it shows on the fly, re-scanning the tick table on every refresh. That table only
grows, so the dashboard gets slower forever.

There are also no tests and no CI at all.

This design adds the missing transform step as a `rollup` service, points the
dashboard at its output, and puts a test suite and a GitHub Actions workflow
around the whole thing.

## Current state

```
Finnhub websocket
       │
       ▼
   ┌────────┐        ┌──────────────────────┐        ┌───────────┐
   │ stream │ ─────▶ │ destination_postgres │ ◀───── │ dashboard │
   └────────┘        │  raw_trades          │        │ Streamlit │
                     │  stream_sessions     │        └───────────┘
                     └──────────────────────┘
```

`stream` runs a socket thread that parses messages onto an in-memory queue, and
a main-thread loop that drains the queue into Postgres once a second. It also
writes a heartbeat to `stream_sessions` on every flush, which is what lets the
dashboard tell "quiet market" apart from "dead socket".

## Target state

```
Finnhub websocket
       │
       ▼
   ┌────────┐        ┌──────────────────────┐        ┌───────────┐
   │ stream │ ─────▶ │ destination_postgres │ ◀───── │ dashboard │
   └────────┘        │  raw_trades          │        │ Streamlit │
                     │  stream_sessions     │        └───────────┘
   ┌────────┐        │  trades_1m      (new)│
   │ rollup │ ◀────▶ │  rollup_runs    (new)│
   └────────┘        └──────────────────────┘
```

`rollup` reads raw ticks and writes one-minute OHLCV candles back to the same
database. The dashboard's history chart reads candles instead of ticks.

---

## 1. The `rollup` service

A new top-level folder, built the same way as `stream/`: small single-purpose
files, its own `Dockerfile` and `requirements.txt`, no package shared with the
other services.

```
rollup/
  Dockerfile
  .dockerignore
  requirements.txt
  config.py      env vars + validation
  db.py          engine + apply_schema
  schema.sql     trades_1m + rollup_runs
  candles.py     pure function: trades frame -> candles frame
  writer.py      the upsert, and run logging
  main.py        the loop
```

### Schema

```sql
CREATE TABLE IF NOT EXISTS trades_1m (
    symbol      TEXT        NOT NULL,
    minute      TIMESTAMPTZ NOT NULL,
    open        NUMERIC     NOT NULL,
    high        NUMERIC     NOT NULL,
    low         NUMERIC     NOT NULL,
    close       NUMERIC     NOT NULL,
    volume      NUMERIC     NOT NULL,
    trade_count INTEGER     NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, minute)
);

CREATE TABLE IF NOT EXISTS rollup_runs (
    run_id          BIGSERIAL   PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    window_start    TIMESTAMPTZ,
    window_end      TIMESTAMPTZ,
    trades_read     BIGINT      DEFAULT 0,
    minutes_written BIGINT      DEFAULT 0,
    status          TEXT        NOT NULL,
    error_message   TEXT
);
```

The composite primary key `(symbol, minute)` is the mechanism the whole design
rests on — it is what makes `ON CONFLICT DO UPDATE` possible, and therefore what
makes the job safe to re-run.

`rollup_runs` mirrors the existing `stream_sessions` idea: a failed run is
visible in the dashboard instead of buried in container logs.

### The loop

Every `ROLLUP_INTERVAL_SECONDS` (default 60):

1. Read `raw_trades` where `trade_ts >= now() - ROLLUP_WINDOW_MINUTES`,
   `LIMIT ROLLUP_MAX_ROWS` as a safety net so one runaway window cannot pull an
   unbounded result into memory.
2. Group by `(symbol, minute)` in pandas → open, high, low, close, volume, count.
3. `INSERT ... ON CONFLICT (symbol, minute) DO UPDATE` every resulting row.
4. Write the run to `rollup_runs`. Sleep.

`build_candles` has the signature:

```
build_candles(frame) -> frame
```

Input columns: `symbol`, `trade_ts` (timezone-aware), `price`, `volume` — that
is, the raw rows exactly as they come out of `raw_trades`. Truncating `trade_ts`
to the minute happens **inside** the function, so the caller does no data work
and the function is testable from raw input alone.

Output columns: `symbol`, `minute`, `open`, `high`, `low`, `close`, `volume`,
`trade_count`.

Candle fields, per `(symbol, minute)` group:

| Field | Definition |
|---|---|
| `open` | price of the **earliest** trade in the minute |
| `high` | max price |
| `low` | min price |
| `close` | price of the **latest** trade in the minute |
| `volume` | sum of `volume` |
| `trade_count` | number of trades |

### Handling late trades

The stream writes a trade up to a second after it happened, and Finnhub itself
can deliver late. So at 10:05:00 the candle for 10:04 may still be missing rows.

Each run therefore re-aggregates a **trailing window** (default 10 minutes) and
upserts the result. The older nine minutes are rewritten with identical values;
the newest minute gets corrected. Late arrivals are folded in automatically.

Two consequences worth stating explicitly:

- **The job is idempotent.** Running it twice in a row changes nothing. This is
  a testable property, not just a nice one.
- **The newest candle is deliberately partial.** The current minute is still
  filling. It is written anyway so the dashboard stays live, and the next run
  overwrites it with the finished version.

### Why pandas rather than one SQL `GROUP BY`

A single server-side query could do this and move no data over the wire. It is
rejected here on purpose: 10 minutes × 5 symbols is a few thousand rows, which
is nothing, and computing it in pandas makes `build_candles(frame) -> frame` a
pure function with no database in it — by far the easiest thing in the project
to test properly.

This trade-off flips at scale. A comment in `candles.py` will record that at
several hundred symbols the aggregation belongs in SQL.

### Failure handling

One bad run must never kill the loop. The body is wrapped in `try/except`;
failures are recorded as `status='failed'` with the error message in
`rollup_runs`, then the loop sleeps and continues. Same spirit as
`safe_market_status` in `stream/main.py`.

### Configuration

Read from environment, validated at startup, following the exact shape of
`stream/config.py` (a `DEFAULTS` dict, a `ConfigError`, a frozen dataclass):

| Variable | Default | Meaning |
|---|---|---|
| `ROLLUP_INTERVAL_SECONDS` | `60` | How often the loop runs |
| `ROLLUP_WINDOW_MINUTES` | `10` | Size of the trailing re-aggregation window |
| `ROLLUP_MAX_ROWS` | `200000` | Safety cap on rows read per run |

Validation rules: interval > 0, window >= 1, max rows >= 1.

---

## 2. Dashboard changes

Two changes, no new dependencies.

### History chart reads `trades_1m`

Currently `dashboard/app.py` derives per-minute prices from every raw tick:

```sql
SELECT DISTINCT ON (symbol, date_trunc('minute', trade_ts))
       symbol, date_trunc('minute', trade_ts) AS at, price
  FROM raw_trades
 WHERE trade_ts >= now() - make_interval(hours => :hours)
```

It becomes a primary-key read:

```sql
SELECT symbol, minute AS at, close AS price
  FROM trades_1m
 WHERE minute >= now() - make_interval(hours => :hours)
 ORDER BY symbol, minute
```

`HISTORY_SQL` is currently defined but `render_chart` is never called from the
`live()` fragment — the history chart is only half-wired. Finishing that
connection is part of this work.

### Rollup health

The existing "Stream health" expander gains a sibling showing the last rollup
run, minutes written, and a warning when the last run failed or the newest
candle is more than a few minutes old. Reuses the existing `format_age` and
`seconds_since` helpers.

### Graceful degradation

If `trades_1m` does not exist, the page shows a hint and skips the chart, using
the `table_exists` guard already present in `app.py`. Running the dashboard
without the rollup service must not crash.

### Out of scope

A real candlestick chart. `st.line_chart` cannot draw one, so it would require
adding plotly — a separate decision from the pipeline work.

---

## 3. Testing

### Layout

```
tests/
  conftest.py            shared fixtures; puts stream/ and rollup/ on sys.path
  unit/
    test_stream_config.py
    test_rollup_config.py
    test_parse_message.py
    test_buffer.py
    test_backoff.py
    test_market_status.py
    test_socket_events.py
    test_candles.py
  integration/
    test_stream_writer.py
    test_rollup_writer.py
    test_schema.py
requirements-dev.txt     pytest, pytest-cov, ruff, pandas, sqlalchemy, psycopg2-binary
pyproject.toml           pytest, coverage, and ruff configuration
```

Tests live at the repo root, outside the service folders, so they are never
copied into the Docker images.

Because the services are independent projects with no shared package,
`conftest.py` appends `stream/` and `rollup/` to `sys.path` so their modules
import by their real names (`from config import load_config`), exactly as they
do inside their containers.

### Unit tests (no database, no network)

| Target | Cases |
|---|---|
| `parse_symbols` | lowercase → upper, duplicates removed, blanks skipped, all-blank raises `ConfigError` |
| `load_config` (stream) | defaults applied; unparseable number raises; timeout <= 0 raises; `reconnect_max < reconnect_min` raises; `stale_after <= flush_interval` raises; missing `FINNHUB_API_KEY` raises |
| `load_config` (rollup) | defaults applied; interval <= 0 raises; window < 1 raises |
| `parse_message` | trade message → `Trade` tuple; ping message → no trades; malformed JSON → `ERROR`, no exception; missing `v`/`c` fields default correctly; millisecond epoch converts to the right UTC datetime |
| `drain` | empty queue returns empty; fewer items than max; more items than max returns exactly max; never blocks |
| `ExponentialBackoff` | delay grows with attempts; caps at `max_seconds`; jitter falls in `[capped/2, capped]`; `reset()` returns attempts to zero; both methods return **new** objects and do not mutate the original |
| `fetch_market_status` | fake session: normal payload parses; missing fields tolerated; HTTP error propagates to the caller |
| `SocketEvents.record` | trade counting accumulates; `failed` stores the error; `closed` sets the event flag |
| `build_candles` | empty input returns empty; single trade; **shuffled input still yields correct open/close**; minute boundaries assign correctly; multiple symbols stay separate; out-of-order timestamps |

`build_candles` is the most important of these. Open and close depend on
ordering, so the shuffled-input case is what separates a real test from one that
passes by accident.

### Integration tests (real Postgres)

Mocking SQLAlchemy would prove nothing — the bugs in this project live in SQL.

- `insert_trades`: batch write lands all rows; empty batch is a no-op returning 0
- `start_session` returns a usable id; `finish_session` sets status and timestamp
- `heartbeat` with `market_open=None` **does not** overwrite a stored value —
  this is what the `COALESCE` in `stream/writer.py` exists for, and it is subtle
  enough to deserve an explicit test
- `heartbeat` with an older `last_message_at` does not move the timestamp
  backwards, per the `GREATEST` in the same statement
- `apply_schema` run twice is safe
- rollup upsert: inserts new minutes; updates existing ones in place; running the
  same batch twice leaves the table unchanged (idempotence)

### Database fixture

The fixture reads a single environment variable, `TEST_DATABASE_URL`, and if it
is unset falls back to the compose database on `localhost:5434`.

- **In CI:** GitHub Actions supplies a `postgres:13` service container on
  `localhost:5432`, and the workflow sets `TEST_DATABASE_URL` accordingly.
- **Locally:** `docker compose up -d destination_postgres` publishes the same
  image on `localhost:5434`, which the fallback already points at, so `pytest`
  works with no extra setup.

Each integration test runs inside a transaction that is rolled back at the end,
so tests never leave rows behind and never depend on each other's order.

If no database is reachable, integration tests **skip** rather than fail, so
`pytest` still works offline.

`testcontainers` is deliberately not used: it is heavier than this project needs
and the development machine has 8 GB of RAM.

### Coverage

80% floor, enforced with `--cov-fail-under=80`.

`stream/main.py`'s infinite loop and `dashboard/app.py` are excluded from the
measurement. Covering them requires brittle tests that break on every refactor
and demonstrate very little. The pure modules and the writers should be at or
near 100%, and that is the number worth defending.

### Known issue this exposes but does not fix

`raw_trades` has no unique constraint, so a socket reconnect that replays trades
stores them twice, which would inflate a candle's `volume` and `trade_count`.
The tests will make this behaviour visible and documented. Fixing it belongs to
a separate data-quality change and is out of scope here.

---

## 4. CI

`.github/workflows/ci.yml`, triggered on push and pull request, Python 3.11
(matching every Dockerfile), with two jobs.

### `lint`

`ruff check` over `stream/`, `rollup/`, `dashboard/`, and `tests/`.

**`ruff format` is deliberately not run.** The existing code has a consistent
hand-written style — blank lines between logical blocks, inline explanatory
comments. Running the formatter would reflow the entire codebase in one enormous
diff and bury the actual feature. Linting catches real defects (unused imports,
undefined names, shadowed builtins); formatting is cosmetic and can be decided
separately, on purpose.

### `test`

```yaml
services:
  postgres:
    image: postgres:13
    env:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: test_db
    options: >-
      --health-cmd pg_isready --health-interval 5s
      --health-timeout 3s --health-retries 20
    ports: ['5432:5432']
```

Runs `pytest` with coverage against that database.

**No Finnhub API key is required anywhere in CI.** Every test uses either a pure
function or a fake HTTP session. This matters: it means CI works on forks and on
pull requests, where repository secrets are not available.

Pip downloads are cached via `actions/setup-python`, keeping runs to a couple of
minutes.

### Out of scope

A docker build job and a full compose smoke test. Both are straightforward to
add later as extra jobs.

---

## 5. Cleanup

Included because the repository currently documents software that does not exist.

- **`README.md` rewritten.** It still describes an `ingest/` + `transform/`
  Hugging Face pipeline that was deleted. Anyone reading the repo gets a false
  picture of the project. The new version covers the real architecture, the four
  tables, the actual environment variables, how to run the stack, and how to run
  the tests.
- **`.env.example` corrected.** Remove `POLL_INTERVAL_SECONDS`,
  `FINNHUB_RATE_PER_MINUTE`, `FINNHUB_RATE_BURST`, `FINNHUB_MAX_RETRIES`,
  `BREAKER_FAILURE_THRESHOLD`, `BREAKER_COOLDOWN_SECONDS` — none exist in
  `stream/config.py`. Add the real `FLUSH_*`, `RECONNECT_*`,
  `MARKET_STATUS_INTERVAL_SECONDS`, `STALE_AFTER_SECONDS`, and the new
  `ROLLUP_*` settings.
- **`docker-compose.yaml`** gains the `rollup` service, depending on
  `destination_postgres` being healthy, matching how `stream` is wired.
- **Dead code:** `read_table` in `dashboard/db.py` is never called — delete it.
  `stale_after_seconds` is validated in `stream/config.py` but never used by the
  stream (the dashboard reads its own copy from environment) — either use it in
  the stream's staleness logging or remove it from the config.

---

## Build order

Implementation should follow this sequence, so that each step is verifiable
before the next begins:

1. Test scaffolding — `requirements-dev.txt`, `pyproject.toml`, `conftest.py`.
2. Unit tests for the existing `stream` modules. These pass immediately against
   code that already works, and prove the harness is sound.
3. Integration tests for `stream/writer.py` against a real Postgres.
4. `tests/unit/test_candles.py` — written **before** `build_candles` exists, and
   failing.
5. `rollup/candles.py` until those tests pass.
6. The rest of the rollup service: `config.py`, `schema.sql`, `db.py`,
   `writer.py`, `main.py`, plus its integration tests.
7. `Dockerfile` and the compose entry.
8. Dashboard changes.
9. CI workflow.
10. README, `.env.example`, and dead-code cleanup.

## Success criteria

- `pytest` passes locally and in CI, with coverage at or above 80%.
- `ruff check` is clean.
- `docker compose up --build` brings up postgres, stream, rollup, and dashboard;
  candles appear in `trades_1m` within two minutes of the first trade landing in
  `raw_trades`. (Nothing arrives while the US market is closed, so verifying this
  end to end requires an open market — or seeding `raw_trades` by hand, which the
  integration tests already do.)
- Running the rollup twice against unchanged data leaves `trades_1m` unchanged.
- The dashboard history chart renders from `trades_1m`, and still loads without
  crashing when that table does not exist.
- `README.md` describes the software that is actually in the repository.
