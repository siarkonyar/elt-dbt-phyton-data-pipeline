# Project Map

## Purpose
Live stock-trade pipeline on Finnhub data: stream trades into Postgres, roll them
up into candles, serve them through an api, and show them on a dashboard with
login and price alerts.

## Requirements
- Learner wants to add Redis, mainly to learn Redis.
- First Redis use (chosen 2026-10-07): live prices for the dashboard's live board.
- If Redis is down or empty, the live board falls back to Postgres (chosen 2026-10-07).
- Confirmed design (not implemented): stream writes one hash per symbol every
  flush; dashboard reads it. If a symbol's hash is missing, stream seeds day stats
  from Postgres once. No Redis persistence — Redis is a rebuildable cache.
- Confirmed (not implemented): hash holds `day`; "today" = New York
  (America/New_York) date of the trade timestamp, chosen 2026-10-09 — LATEST_SQL
  must use the same day; missing OR wrong-day hash -> seed from Postgres; dashboard blanks day
  stats when hash.day != today. REDIS_URL defaults to redis://redis:6379/0 in code.

## Components
- `stream/` — Finnhub websocket -> in-memory queue -> flush loop writes `raw_trades`
  once a second, heartbeats `stream_sessions`, checks price alerts (`stream/main.py`).
- `rollup/` — every interval, reads recent trades and upserts `candles`, logs `rollup_runs`.
- `api/` — FastAPI: `/health`, `/candles`, `/auth/login`, `/auth/register`, `/alerts`
  (create/list/delete). JWT auth (`api/tokens.py`, HS256).
- `dashboard/` — Streamlit. Reads Postgres directly for prices/status (`dashboard/data.py`),
  talks to the api for auth and alerts. Live board re-runs on a timer
  (`dashboard/views/markets.py:live_board`) and runs `LATEST_SQL` each time.
- `destination_postgres` — Postgres 13, the only datastore today.

## Main Flow
```
Finnhub ws --trades--> stream --insert every 1s--> Postgres (raw_trades)
                          |--check alerts--> Postgres (price_alerts)
Postgres --recent trades--> rollup --upsert--> Postgres (candles)
dashboard --LATEST_SQL every refresh--> Postgres
dashboard --login / alerts--> api --> Postgres
Redis: service implemented in compose (step 1). No code reads or writes it yet.
Chosen (not built): stream --hash per symbol every flush--> Redis --> dashboard
                   (missing/old hash -> stream seeds day stats from Postgres)
```

## Data and Trust Boundaries
- Postgres holds all data; password from `.env` (`POSTGRES_PASSWORD`).
- Finnhub API key in `.env`.
- Users authenticate via api; JWT signed with a secret from config.

## Build and Deployment
- `docker-compose.yaml`: destination_postgres, redis, stream, rollup, api, dashboard on `elt_network`.
  redis: `redis:7-alpine`, persistence off, host port 127.0.0.1:6379; e2e remaps it.
- CI: `.github/workflows/ci.yml` (ruff) and `service-tests.yml` (unit + integration per service).
- Dev deps: `requirements-dev.txt`. Tests under `tests/unit`, `tests/integration`, `tests/e2e`.
- README.md describes an older Hugging Face pipeline and is out of date.

## Unknowns
- How Redis gets its live-price data and what it stores (open design question).
- What happens to day stats (open/high/low/count) if Redis restarts mid-day (open question).
- Redis client library, key layout, expiry, compose wiring, testing approach.
