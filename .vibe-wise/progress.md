# Learning Progress

## Redis basics
- Introduced (Claude explained): Redis is an in-memory key-value store; hashes,
  EXPIRE; Postgres vs Redis (durable archive vs fast temporary copy); common uses
  (cache, rate limiting, queue, pub/sub).
- Demonstrated understanding: none yet.

- Introduced (Claude explained, 2026-10-07): key types (string, hash), TTL,
  atomic commands (INCR/HINCRBY/HSETNX) vs read-modify-write, pipelines,
  RAM durability.

## Live-price design
- Learner proposed (2026-10-07): stream writes one hash per symbol every flush;
  dashboard reads it instead of the database (Postgres fallback agreed earlier).
  Matches the layout Claude sketched earlier; learner adopted it.

- Learner identified (2026-10-07): after a mid-day Redis restart the day stats
  would be wrong. Asked for help on how to fix it.
- Claude offered options (proposals, not decisions): A) seed missing hash from
  Postgres in stream; B) Redis persistence (AOF/RDB); C) `since` field so the
  dashboard detects partial day stats and asks Postgres.

- Learner chose A (seed missing hash from Postgres), 2026-10-07. No reason given yet.
- Learner floated B / "Redis as the database itself" and asked for Claude's view.
  Claude recommended A only (live prices are rebuildable -> cache; persistence
  matters for primary-store data like a future alert queue). Recommendation, not
  a learner decision.
- Introduced (Claude explained): cache vs primary store; why Postgres stays the
  source of truth (SQL queries, history, durability).

- Learner decided (2026-10-07): A only, no Redis persistence for live prices
  ("the traditional path"). No explicit reason stated beyond accepting the
  cache framing.

- Learner proposed (2026-10-07): store `day` in the hash; reset day stats when it changes.
- Claude proposed, learner confirmed after discussing #2 (2026-10-08): "today" =
  UTC date of the trade timestamp; wrong-day handled like missing hash (seed from
  Postgres); dashboard blanks day stats when hash.day != today.
- Learner reopened the day definition (2026-10-09) and asked how UK platforms do
  it; Claude researched (T212/Freetrade: change from open, premarket excluded or
  separate; eToro: vs previous close, extended hours separate; all anchor on the
  NY session). Learner chose: day = New York calendar date of the trade
  (America/New_York), "keep it simple". Supersedes "UTC date". LATEST_SQL must
  switch to the NY day too (step 3).
- Learner reversed (2026-10-09): keep UTC, no New York conversion (after Claude
  explained tzdata/zoneinfo). "today" = UTC date of the trade; LATEST_SQL unchanged.
  Learner accepted the edge case: in winter one batch may span UTC midnight and
  merge treats it as one day.
- Learner pushed back on a separate new_york_day helper (YAGNI) — valid; dropped.
- Learner chose (2026-10-08): REDIS_URL has a default in code
  (redis://redis:6379/0); .env only overrides it.
- Introduced (Claude explained): what a connection URL is (protocol/host/port/db),
  compose service names as hosts, why addresses come from env.
- Build order agreed implicitly via step-1 approval only: 1 redis service,
  2 stream writer (learner writes the merge function), 3 dashboard reader, 4 tests.
- Step 1 implemented (2026-10-07): redis service in compose (no persistence,
  127.0.0.1:6379, healthcheck), stream depends_on redis, REDIS_URL in .env.example,
  e2e port override for redis. Compose config validated; containers not started.

## Seed/merge ordering
- Learner was stuck on why seeding after insert double-counts; Claude walked
  through numbers and explained idempotent operations (max/min/keep-first vs add).
- Learner decided (2026-10-08): seed BEFORE inserting into Postgres.
- Learner decided (2026-10-08): only write to Redis if the Postgres insert succeeds.
- Resulting flush order (confirmed): read Redis / seed if missing or old day ->
  insert into Postgres -> on success, merge and write Redis.

## Pending decision
- Step 1 not yet committed by learner as of 2026-10-08.
- Merge rules settled by learner (2026-10-09) after a worked example: price/
  volume/trade_ts from latest trade by time; volume = last trade size; day_open
  kept if present else earliest trade; high/low = max/min of old + batch;
  trades_today = old + len(batch). First attempt ignored old values for open/low/
  count; corrected after explanation (Needs reinforcement: combining old state
  with new input).
- Step 2a implemented (2026-10-09): tests/unit/stream/test_live_prices.py (7 tests
  from the learner's table) + stream/live_prices.py merge stub. Verified RED: 7
  fail with NotImplementedError; ruff clean. Run with .venv/bin/python.
- Learner wrote merge (2026-10-09) with hints (max/min with key, old.get).
  First version: missing `return`, attribute access on a dict (old.day_open).
  Fixed after review; 7/7 tests pass. Logic designed and written by learner.
  Remaining: ruff W292 (missing trailing newline) for learner to fix.
- Demonstrated understanding: latest/earliest by time via max/min key; combining
  old state with batch; building a new dict instead of mutating old.
- Needs reinforcement: dict vs attribute access; functions must return.
- Contract to keep in 2b: merge trusts old is from the same day; caller seeds
  when hash is missing or from another day.
- Redis failure rules (learner, 2026-10-09, after Claude explained crash-loop
  and no-timeout behaviour + timeouts/failure isolation): skip the Redis update,
  keep inserting, timeout under a second. Learner chose re-seed after a failure
  (next flush treats every hash as missing).
- Step 2b implemented (2026-10-09): redis==7.0.1; StreamConfig.redis_url with
  default; live_prices.py: REDIS_TIMEOUT_SECONDS=0.5, to_redis/from_redis,
  connect, read_live_prices/write_live_prices (one pipeline each); db.py:
  DAY_STATS_SQL + read_day_stats (one query for all symbols, UTC day range).
  Unit: 321 pass, ruff clean. Integration test_day_stats.py written but SKIPPED
  (no local test DB). Redis read/write untested until step 4.
- Learner asked for line-by-line explanations of DAY_STATS_SQL (SQL execution
  order, ANY, range filter + index, GROUP BY, array_agg ORDER BY [1]) and of
  zip(..., strict=True) over pipe.execute(). Introduced, not yet demonstrated.
- Steps 1, 2a, 2b committed by learner (f4b8949, 5f8af5c, 24e7ff0).
- Step 2c implemented (2026-10-09): load_live_prices/save_live_prices in
  stream/main.py (log-and-carry-on like check_alerts); flush_loop loads before
  insert, saves in try/else only after a successful insert with trades;
  needs_reseed starts True per loop and is set when load or save fails.
  7 new unit tests; 328 unit pass, ruff clean. Flag lines in flush_loop not
  unit-tested (step 4 integration/e2e). Not run against a real Redis yet.
- Step 3 decisions (learner, 2026-10-12): symbol list from STOCK_SYMBOLS, not a
  SCAN (first picked SCAN, switched after the stale-key drawback); then asked
  for STOCK_SYMBOLS as a code constant, not env (accepted manual sync risk);
  whole-board fallback to LATEST_SQL when any symbol is missing or Redis errors.
- Introduced (Claude explained): KEYS vs SCAN (blocking), TTL as the usual
  answer to stale keys.
- Step 3 implemented (2026-10-12): dashboard/live_prices.py (STOCK_SYMBOLS
  constant, read_live_board -> LATEST_SQL-shaped frame or None, blanks day stats
  when hash.day != UTC today); data.live_board (Redis, else latest());
  ui.redis_client (cache_resource, REDIS_URL env default); markets.live_board
  uses it; pipeline page unchanged (still data.latest). 5 new unit tests incl.
  symbols == stream default; 333 unit pass, ruff clean. Streamlit wiring only
  compiled (streamlit not in .venv), not run.
- Before step 3: dashboard symbol source — STOCK_SYMBOLS from .env vs SCAN price:* keys.
