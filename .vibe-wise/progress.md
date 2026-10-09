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
- Learner now writes merge(old, trades) to make the tests pass.
- Before step 3: dashboard symbol source — STOCK_SYMBOLS from .env vs SCAN price:* keys.
