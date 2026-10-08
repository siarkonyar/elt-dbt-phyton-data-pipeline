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
- Claude proposed additions (not yet confirmed by learner): "today" = UTC date of
  the trade timestamp; wrong-day handled like missing hash (seed from Postgres);
  dashboard blanks day stats when hash.day != today.
- Build order agreed implicitly via step-1 approval only: 1 redis service,
  2 stream writer (learner writes the merge function), 3 dashboard reader, 4 tests.
- Step 1 implemented (2026-10-07): redis service in compose (no persistence,
  127.0.0.1:6379, healthcheck), stream depends_on redis, REDIS_URL in .env.example,
  e2e port override for redis. Compose config validated; containers not started.

## Pending decision
- Awaiting "continue" after step 1 (learner runs docker + redis-cli and commits).
- Before step 2: confirm or change Claude's proposed additions for day rollover.
- Before step 3: dashboard symbol source — STOCK_SYMBOLS from .env vs SCAN price:* keys.
