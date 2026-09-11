# Plan: add a read-only `api` service, test-first

## Context

Right now the only way to see what this pipeline produces is the Streamlit
dashboard. The data has no front door — nothing else can read it.

This plan adds a fifth service, `api/`, that serves the `candles` table as
JSON over HTTP. It reads. It never writes. That is what keeps it small.

The point of the exercise is the TDD loop, not the service. So the steps
below are ordered **red, green, refactor** — every step names the test you
write first, the failure you should see, and only then the code that makes
it pass. If you ever find yourself writing code before a failing test,
you have skipped a step.

Where it sits:

```
fake_websocket → stream → raw_trades → rollup → candles ─┬→ dashboard (:8501)
                              (postgres)                 └→ api       (:8000)  ← new
```

The payoff is in the last step: the e2e test asserts the OHLC
`(100.0, 108.0, 95.0, 104.0)` — the exact numbers
`test_candle_has_the_expected_ohlc` already checks — but arriving over
HTTP through a brand-new door.

---

## Decisions already made

These are settled. Written down so you do not re-litigate them at 1am.

| Decision | Why |
|---|---|
| FastAPI + uvicorn | Validates query params for you; `TestClient` makes route tests one line |
| Two endpoints only: `/health`, `/candles` | YAGNI. `/symbols` and `/trades` can come later |
| Unknown symbol → `200` with `[]` | "No candles yet" is a normal state, not an error. A 404 would make callers treat it as a failure |
| `/health` does not touch the database | It proves the container is up, same as the dashboard's `/_stcore/health`. A health check that dies when Postgres blinks makes restarts worse |
| Missing `candles` table → let it raise a 500 | That is a genuine failure. Returning `[]` would silently swallow it |
| The engine is built lazily, not at import | Importing `main.py` in a unit test must not try to reach Postgres |

---

## The shape of the code

Six new files in `api/`. Flat directory, bare imports, own Dockerfile —
identical in shape to `dashboard/` and `rollup/`.

| File | What is in it | Rough size |
|---|---|---|
| `api/serialize.py` | `candle_to_dict(row)` — the pure bit | ~12 lines |
| `api/queries.py` | one `CANDLES_SQL` statement | ~12 lines |
| `api/db.py` | `get_engine(env=None)`, `read_candles(engine, symbol, hours)` | ~35 lines |
| `api/main.py` | the FastAPI app and two routes | ~40 lines |
| `api/Dockerfile` | uvicorn on 8000 | ~13 lines |
| `api/requirements.txt` | fastapi, uvicorn, SQLAlchemy, psycopg2-binary | 4 lines |

The dependency chain is deliberately one-way:

```
main.py  →  db.py  →  queries.py
   └──────→ serialize.py
```

`serialize.py` and `queries.py` import nothing of yours. That is why they
are the easiest things to test, and why you write them first.

---

## What goes in each `api/` file

Responsibilities, signatures and constraints — not finished code. You write
the bodies; the tests in each step tell you exactly what they must do.

### `api/queries.py` — the SQL, and nothing else

**Contains:** a module docstring and one constant, `CANDLES_SQL = text(...)`.

**The statement:**

```sql
SELECT symbol, minute, open, high, low, close, volume, trade_count
  FROM candles
 WHERE symbol = :symbol
   AND minute >= now() - make_interval(hours => :hours)
 ORDER BY minute
```

**Why it is its own file:** the same reason `dashboard/queries.py` exists —
a test can import it and assert against the SQL the service really runs,
without starting anything. It imports only `sqlalchemy.text`. Nothing of
yours.

**Style to match:** put a comment above the statement explaining the index
choice — `candles_idx` is on `minute DESC`, and the primary key leads with
`symbol`, so it cannot serve a range scan on `minute` alone.

**Must not:** contain functions, open connections, or take parameters.

### `api/db.py` — everything that talks to Postgres

**Contains:** two functions with very different testing needs.

`get_engine(env=None)`
- Reads `DESTINATION_POSTGRES_HOST` (default `destination_postgres`),
  `_PORT` (`5432`), `_DB` (`destination_db`), `_USER` (`postgres`) and
  `_PASSWORD` (no default).
- Raises `RuntimeError` naming the api service if the password is missing.
- Otherwise builds the `postgresql+psycopg2://...` URL and returns
  `create_engine(url)`.
- Copy `rollup/db.py`'s version; change only the error message.
- **Takes `env` as an argument, never reads `os.environ` directly.** That
  is what lets a test hand it a plain dict.
- **This function is unit-testable**, even though it lives in `db.py`.
  `create_engine()` is lazy — it opens no connection until you call
  `.connect()`. See Step 3a.

`read_candles(engine, symbol, hours)`
- Opens a connection, runs `CANDLES_SQL` with `{"symbol": ..., "hours": ...}`,
  returns `.all()` — raw SQLAlchemy `Row` objects.
- Needs a real database, so it is covered by the integration tests in
  Step 3b.

**Must not:** convert anything. It returns rows exactly as Postgres gave
them — `Decimal` prices, `datetime` minutes. Converting is the next file's
job.

### `api/serialize.py` — the pure one

**Contains:** one function, `candle_to_dict(row)`, returning a dict with
exactly eight keys.

**What it does:**

| Field | In (from Postgres) | Out |
|---|---|---|
| `open`, `high`, `low`, `close`, `volume` | `Decimal` | `float` |
| `trade_count` | `int` | `int` |
| `minute` | tz-aware `datetime` | ISO string, `+00:00` not `Z` |
| `symbol` | `str` | unchanged |

**Why it exists:** Postgres `NUMERIC` comes back as `Decimal`, and
`json.dumps` has no idea what a `Decimal` is. Without this you get a 500
the first time anyone calls the endpoint. That is the bug this file
prevents.

**Why it is separate:** it imports nothing — not your code, not
SQLAlchemy, not FastAPI. Fastest thing in the repo to test, so it is the
first thing you write.

**Must not:** touch a database, know about HTTP, or contain an `if`. One
dict literal. If you are writing a branch, a test is missing.

### `api/main.py` — the HTTP layer

**Contains:** the app, three small functions, and two routes.

`app = FastAPI(title=...)` — created at import. No side effects.

`_engine()` — wrapped in `@lru_cache(maxsize=1)`, returns `db.get_engine()`.
**Load-bearing:** a unit test imports this module, and importing it must
never try to reach Postgres. The cache also means one engine for the
process, not one per request.

`read_candles(symbol, hours)` — glues `_engine()` to `db.read_candles`.

`get_reader()` — returns that function. **This is the seam.** Tests swap it
out with `app.dependency_overrides`, which is why the route tests need no
database and no mocking library.

`GET /health` — returns `{"status": "ok"}`. Three lines. Touches nothing,
by design: a health check that dies when Postgres blinks makes restarts
worse, not better.

`GET /candles` — declares its two params so FastAPI validates them before
your code runs:

```python
symbol: str = Query(..., min_length=1, max_length=10)
hours: int = Query(1, ge=1, le=24)
reader=Depends(get_reader)
```

The body is one list comprehension: upper-case the symbol, call the
reader, map `serialize.candle_to_dict` over the rows.

**Must not:** contain SQL, handle `Decimal`, or manage connections. If the
route body grows past five lines, something belongs in `db.py` or
`serialize.py`.

### `api/Dockerfile`

`rollup/Dockerfile` verbatim, with two changes at the bottom:

```dockerfile
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`main:app` means "the object named `app` inside `main.py`". `0.0.0.0`
rather than `localhost`, because inside a container `localhost` is
invisible to every other container — same note as the bottom of
`tests/e2e/fake_websocket/app.py`.

### `api/requirements.txt`

Four lines. See Step 5 for the pins and for why `uvicorn` belongs here but
not in `requirements-dev.txt`.

### Deliberately absent

**No `config.py`.** Your other services have one because they have real
settings — flush intervals, reconnect windows, symbol lists. This service
has none. Its only configuration is the database connection, and `db.py`
reads that itself. A config module for zero settings is ceremony.

**No `schema.sql`.** The API only reads. `rollup/` owns the `candles`
table and creates it.

**No `__init__.py`.** Flat directory, bare imports, exactly like `rollup/`
and `dashboard/`.

**No writes anywhere.** That single constraint is what keeps the whole
service under 150 lines.

---

## Step 0 — Prepare (no tests yet)

Two edits, so the tests you are about to write can even run.

**`requirements-dev.txt`** — add two lines:

```
fastapi==<pin whatever pip installs>
httpx==<pin whatever pip installs>
```

`httpx` is not optional. FastAPI's `TestClient` is built on it and will
raise on import without it.

**`pyproject.toml`** — two one-word edits:

```toml
[tool.coverage.run]
source = ["stream", "api"]

[tool.ruff]
src = [".", "api", "dashboard", "rollup", "stream"]
```

Without the ruff change, ruff thinks `from db import ...` inside `api/`
is a third-party package and sorts your imports wrong.

Then:

```bash
pip install -r requirements-dev.txt
```

---

## Step 1 — `candle_to_dict` (unit)

The pure function. No database, no HTTP, no FastAPI.

### RED — `tests/unit/test_api_serialize.py`

Build a fake row with `types.SimpleNamespace`. A real Postgres row is
just an object with attributes, and the numeric columns come back as
`Decimal` — that is the whole reason this function exists.

```python
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
```

Write a `candle_row(**overrides)` helper that returns a `SimpleNamespace`
with sensible defaults, so each test only states what it cares about.

Tests to write, in this order:

1. `test_numeric_prices_become_plain_floats`
   `Decimal("100.00")` in → `100.0` out, and `isinstance(..., float)`.
   **This is the bug this function exists to prevent** — `json.dumps`
   refuses to serialise a `Decimal` and you would get a 500 in production.
2. `test_trade_count_is_an_int`
3. `test_the_minute_becomes_an_iso_string`
   A tz-aware `datetime` in → `"2026-09-07T12:00:00+00:00"` out.
   Note the `+00:00`, **not** `Z` — that is what Python's `.isoformat()`
   actually produces. Assert what is true, not what looks nice.
4. `test_the_symbol_is_passed_through_unchanged`
5. `test_the_result_has_exactly_the_expected_keys`
   `set(result) == {"symbol", "minute", "open", "high", "low", "close",
   "volume", "trade_count"}`. This is your contract test — it fails the
   day someone adds a column and forgets the API.

Run it and **watch it fail**:

```bash
pytest tests/unit/test_api_serialize.py -v
```

The first failure will be the fixture, not the function — these tests
reach the module through a conftest fixture that does not exist yet. Add
the four-line `api_serialize` fixture from Step 2 now, then run again and
watch it fail properly on the missing module.

### GREEN — `api/serialize.py`

One function, one dict literal, `float()` and `int()` and `.isoformat()`.
No branching. If you find yourself writing an `if`, a test is missing.

---

## Step 2 — Wire the test fixtures

`api/main.py` will do `from db import ...` and `from queries import ...`.
Those bare names are already taken: `tests/conftest.py` puts `stream/` and
`rollup/` on `sys.path`, so in one test process `db` means `stream/db.py`.

Your repo already solves this. Copy the pattern, do not invent a new one.

### `tests/conftest.py`

Add three fixtures next to the existing `rollup_*` ones, all using the
existing `_load_service_module` helper:

```python
@pytest.fixture(scope="session")
def api_serialize():
    return _load_service_module("api", "serialize")

@pytest.fixture(scope="session")
def api_queries():
    return _load_service_module("api", "queries")

@pytest.fixture(scope="session")
def api_db():
    return _load_service_module("api", "db")
```

And one that follows the `rollup_main` shape exactly, because `main.py`
imports the others by bare name:

```python
API_BARE_MODULES = ("db", "queries", "serialize")

@pytest.fixture(scope="session")
def api_main():
    saved = {name: sys.modules.get(name) for name in API_BARE_MODULES}
    for name in API_BARE_MODULES:
        sys.modules[name] = _load_service_module("api", name)
    try:
        return _load_service_module("api", "main")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
```

Read `rollup_main` in `tests/conftest.py` before you write this. It is the
same code with a different service name, and the comment above it explains
why the save/restore dance is necessary.

**Gotcha to know about:** the `db` module `api_main` loads under the bare
name is a *different object* from the one the `api_db` fixture returns.
Never assume patching one affects the other.

Now go back and make Step 1 pass.

---

## Step 3a — `get_engine` (unit)

`db.py` holds two functions, and only one of them needs a database. Do the
cheap one first.

`create_engine()` is lazy: it parses the URL and returns an object, but
opens no socket until something calls `.connect()`. So `get_engine` is a
pure string-building function with one validation rule, and you can test it
in milliseconds.

### RED — `tests/unit/test_api_db.py`

Uses the `api_db` fixture from Step 2. Pass a plain dict as `env`; never
touch the real environment.

1. `test_a_missing_password_is_rejected`
   `env` with no `DESTINATION_POSTGRES_PASSWORD` → `pytest.raises(RuntimeError)`.
   This is the failure that actually happens: `.env` goes missing, the
   container dies at startup, and without this message you have no idea why.
2. `test_an_empty_password_is_rejected`
   `{"DESTINATION_POSTGRES_PASSWORD": ""}` → still `RuntimeError`. An empty
   string is falsy, so this passes for free — but it pins the behaviour down
   so a later refactor to `if "..." not in env` cannot break it silently.
3. `test_the_defaults_are_used_when_only_a_password_is_given`
   Assert the returned engine's URL carries `destination_postgres`, `5432`
   and `destination_db`. Read it off `engine.url` rather than rebuilding
   the string yourself.
4. `test_the_environment_overrides_the_defaults`
   Pass a different host and database, assert they appear in the URL.

Two small warnings:

- **Do not assert on the password.** `str(engine.url)` masks it as `***`.
  Compare `engine.url.host`, `.port`, `.database`, `.username` instead.
- The error message should name the service and how to fix it, like
  `rollup/db.py` does. You can assert on a keyword in the message, but keep
  that assertion loose — testing exact prose makes the test brittle.

```bash
pytest tests/unit/test_api_db.py -v
```

### GREEN

Write `get_engine(env=None)` only. Leave `read_candles` for Step 3b.

---

## Step 3b — `CANDLES_SQL` and `read_candles` (integration)

This step needs a real Postgres. Start it yourself:

```bash
docker compose up -d destination_postgres
```

```bash
docker compose exec destination_postgres createdb -U postgres test_db
```

### RED — `tests/integration/test_api_queries.py`

Use the existing `e2e_db` fixture: it creates the schema, empties the
tables before and after, and hands you an engine. Copy the seeding style
from `tests/integration/test_candle_pipeline.py` — it already shows the
`base_minute()` helper and the committed `with engine.begin()` insert,
except here you insert **candles** directly rather than raw trades.

Write an `insert_candles(engine, rows)` helper. The table needs all eight
NOT NULL columns: `symbol`, `minute`, `open`, `high`, `low`, `close`,
`volume`, `trade_count`.

Tests, in this order:

1. `test_returns_the_candles_for_the_requested_symbol`
   Seed NVDA and AMZN. Ask for NVDA. Get one row back.
2. `test_ignores_the_other_symbols`
   Same seed. Assert no AMZN row appears in the NVDA result.
3. `test_a_symbol_with_no_candles_returns_no_rows`
   Ask for `TSLA`. Expect an empty result, **not** an exception. This is
   the test that pins down the "unknown symbol is not an error" decision.
4. `test_candles_older_than_the_window_are_excluded`
   Seed one candle 3 hours old and one 5 minutes old. Ask for
   `hours=1`. Get exactly one row.
5. `test_rows_come_back_oldest_first`
   Seed three minutes out of order. Assert the `minute` values ascend.
   Without an `ORDER BY`, Postgres promises nothing — the same reasoning
   as the sort inside `rollup/candles.py`.

Run it:

```bash
pytest tests/integration/test_api_queries.py -v
```

### GREEN — `api/queries.py` then `api/db.py`

`queries.py` holds one statement, in the style of `dashboard/queries.py`
(module docstring, a comment above the SQL explaining the index choice —
`candles_idx` is on `minute DESC`):

```sql
SELECT symbol, minute, open, high, low, close, volume, trade_count
  FROM candles
 WHERE symbol = :symbol
   AND minute >= now() - make_interval(hours => :hours)
 ORDER BY minute
```

`db.py` gets two functions:

- `get_engine(env=None)` — copy `rollup/db.py`'s version, changing only
  the error message to name the api service. Take `env` as an argument
  rather than reading `os.environ` directly; that is what makes it
  testable.
- `read_candles(engine, symbol, hours)` — opens a connection, executes
  `CANDLES_SQL`, returns `.all()`. No serialising here. One job each.

---

## Step 4 — The routes (unit)

Back to fast tests. No database at all — you fake the reader.

### RED — `tests/unit/test_api_routes.py`

The trick that makes this easy: the route does not depend on an *engine*,
it depends on a *reader function*. Faking a function is trivial; faking a
SQLAlchemy engine is not.

```python
from fastapi.testclient import TestClient

def client(api_main, rows=()):
    """A TestClient whose data source is a list you control."""
    api_main.app.dependency_overrides[api_main.get_reader] = (
        lambda: lambda symbol, hours: list(rows)
    )
    return TestClient(api_main.app)
```

Clear `app.dependency_overrides` in a fixture teardown, or the override
leaks into the next test. `api_main` is session-scoped, so the app object
is shared by every test in the file.

Tests, in this order:

1. `test_health_returns_ok`
   `GET /health` → `200`, body `{"status": "ok"}`.
2. `test_candles_returns_the_serialised_rows`
   One fake row in → one JSON object out, prices as floats.
3. `test_candles_with_no_rows_returns_an_empty_list`
   `200` and `[]`. Not a 404.
4. `test_the_symbol_is_upper_cased_before_the_lookup`
   Request `?symbol=nvda`, record what the fake reader was called with,
   assert it received `"NVDA"`. The table stores upper-case symbols —
   `stream/config.py`'s `parse_symbols` guarantees it.
5. `test_a_missing_symbol_is_rejected`
   `GET /candles` with no query string → `422`. You wrote no code for
   this; FastAPI does it. Test it anyway, so the day someone makes
   `symbol` optional the test says so.
6. `test_a_non_numeric_hours_is_rejected` → `422`.
7. `test_hours_above_the_maximum_is_rejected`
   `?hours=999` → `422`.
8. `test_hours_defaults_to_one_when_absent`
   Assert the fake reader received `1`.

```bash
pytest tests/unit/test_api_routes.py -v
```

### GREEN — `api/main.py`

Four pieces:

```python
@lru_cache(maxsize=1)
def _engine():
    """Built on first use, not at import. A unit test that imports this
    module must never try to reach Postgres."""
    return db.get_engine()

def read_candles(symbol, hours):
    return db.read_candles(_engine(), symbol, hours)

def get_reader():
    """The seam. Tests replace this via app.dependency_overrides."""
    return read_candles

@app.get("/candles")
def candles(
    symbol: str = Query(..., min_length=1, max_length=10),
    hours: int = Query(1, ge=1, le=24),
    reader=Depends(get_reader),
):
    return [serialize.candle_to_dict(row)
            for row in reader(symbol.upper(), hours)]
```

Plus the three-line `/health` route and `app = FastAPI(...)`.

Note what the route does **not** do: no SQL, no `Decimal` handling, no
connection management. Three lines, all delegation. If it grows past
five, something belongs in `db.py` or `serialize.py`.

---

## Step 5 — Containerise it

No tests here. This is plumbing, and the e2e test in Step 6 is what
proves it works.

**`api/requirements.txt`** — pin SQLAlchemy and psycopg2-binary to the
**same versions** already in `requirements-dev.txt` and
`dashboard/requirements.txt`. Two versions of SQLAlchemy across services
is a debugging afternoon you do not want.

```
fastapi==<same pin as requirements-dev.txt>
uvicorn==<pin>
SQLAlchemy==2.0.30
psycopg2-binary==2.9.9
```

Plain `uvicorn`, not `uvicorn[standard]`. The `[standard]` extra pulls in
uvloop, httptools, watchfiles, PyYAML and python-dotenv — speed and
auto-reload extras that a container serving a handful of JSON requests
does not need.

Note that `uvicorn` appears **here only**, not in `requirements-dev.txt`.
It is the web server, and only the container runs one. The unit tests in
Step 4 use FastAPI's `TestClient`, which calls the app directly in-process
over `httpx` — no server involved.

| | `api/requirements.txt` | `requirements-dev.txt` |
|---|---|---|
| fastapi | yes | yes |
| uvicorn | yes | no |
| httpx | no | yes |

(If you ever do install an extra by hand, quote it — zsh treats `[...]`
as a glob and fails with "no matches found": `pip install 'uvicorn[standard]'`.
Inside a requirements file there is no shell, so no quotes are needed.)

**`api/Dockerfile`** — copy `rollup/Dockerfile` and change the last two
lines:

```dockerfile
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`0.0.0.0`, not `localhost` — the same reason the comment at the bottom of
`tests/e2e/fake_websocket/app.py` gives.

**`docker-compose.yaml`** — a new `api` block. Copy the `dashboard` block
and change three things: the build context, the port to `'8000:8000'`,
and nothing else. Keep the `env_file`, the `DESTINATION_POSTGRES_PASSWORD`
line, the network, and `depends_on: destination_postgres: service_healthy`.

Check it by hand before moving on:

```bash
docker compose up -d --build api
```

```bash
curl 'http://localhost:8000/health'
```

---

## Step 6 — The e2e test

The finish line.

**`tests/e2e/docker-compose.e2e.yaml`** — add an `api` block:

```yaml
  api:
    environment:
      DESTINATION_POSTGRES_PASSWORD: e2e
    ports: !override
      - '8000'
```

The `!override` matters for the same reason the comment on
`destination_postgres` explains: without it compose *concatenates* the
port lists and the fixed `8000:8000` from the base file would still be
published, clashing with your dev stack.

**`tests/e2e/conftest.py`** — add `"api"` to `DIAGNOSTIC_SERVICES`. One
word. It means a failure dumps the api container's logs alongside the
others, instead of leaving you guessing.

### RED — two new tests in `tests/e2e/test_full_pipeline.py`

Both depend on the existing `nvda_candle` fixture, so the waiting happens
once and your assertions are deterministic. Follow the style of
`test_dashboard_image_answers_health_check` — it already shows you how to
get the host and port off `compose`.

Add a small helper next to the constants:

```python
API_PORT = 8000
API_TIMEOUT_SECONDS = 10

def api_url(compose, path):
    host = compose.get_service_host("api", API_PORT)
    port = compose.get_service_port("api", API_PORT)
    return f"http://{host}:{port}{path}"
```

1. `test_api_image_answers_health_check`
   `GET /health` → `200`. Proves the image builds, starts and stays up.

2. `test_api_serves_the_candle_over_http`
   `GET /candles?symbol=NVDA&hours=1`, then:
   - status is `200`
   - the body is a list with at least one entry
   - the NVDA entry's `(open, high, low, close)` equals `EXPECTED_OHLC`
   - `trade_count == NVDA_TRADES`

   Reuse the module's existing `EXPECTED_OHLC` and `NVDA_TRADES`
   constants. Do not retype the numbers — if the fixture data ever
   changes, one edit should move every assertion.

Run the whole stack:

```bash
pytest -m e2e -ra
```

First run builds five images and takes a few minutes. Write the tests and
watch them fail *before* you add the compose blocks, so you know the test
can fail.

---

## Step 7 — Tidy up

- **`.github/workflows/ci.yml`** — one stale comment in the `e2e` job now
  reads "Four image builds". It is five. No job changes; the existing
  unit / integration / e2e split already picks up everything you wrote.
- **`README.md`** — add `api` to the service list and document the two
  endpoints with an example `curl`.
- **`ruff`**:

```bash
ruff check .
```

---

## Verification

Run the tiers in order. Each one should be green before you move on.

```bash
pytest -m "not integration and not e2e" --cov -ra
```

```bash
pytest -m integration -ra
```

```bash
pytest -m e2e -ra
```

Then check it by hand against the live dev stack:

```bash
docker compose up -d --build
```

```bash
curl -s 'http://localhost:8000/candles?symbol=NVDA&hours=1' | head
```

```bash
curl -s -o /dev/null -w '%{http_code}\n' 'http://localhost:8000/candles?symbol=NVDA&hours=999'
```

That last one should print `422` — FastAPI rejecting input before your
code runs, which is the thing you chose it for.

Open `http://localhost:8000/docs` for the free interactive page. Nice
thing to put in the README.

---

## Definition of done

- [ ] ~24 new tests, spread across unit / integration / e2e
      (5 serialize + 4 get_engine + 5 queries + 8 routes + 2 e2e)
- [ ] Every one of them was written before the code that makes it pass
- [ ] `pytest -m e2e` green, including the two new API tests
- [ ] `ruff check .` clean
- [ ] Coverage on `api/` above 80%
- [ ] `README.md` documents the new service

## Files touched

**New:** `api/serialize.py`, `api/queries.py`, `api/db.py`,
`api/main.py`, `api/Dockerfile`, `api/requirements.txt`,
`tests/unit/test_api_serialize.py`, `tests/unit/test_api_db.py`,
`tests/unit/test_api_routes.py`, `tests/integration/test_api_queries.py`

**Edited:** `pyproject.toml`, `requirements-dev.txt`, `tests/conftest.py`,
`docker-compose.yaml`, `tests/e2e/docker-compose.e2e.yaml`,
`tests/e2e/conftest.py`, `tests/e2e/test_full_pipeline.py`,
`.github/workflows/ci.yml`, `README.md`
