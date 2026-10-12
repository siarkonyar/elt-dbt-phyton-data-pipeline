<div align="center">

# 📈 Live Stock Trades: a real-time ELT pipeline

**Streams live US stock trades from Finnhub, stores every tick in PostgreSQL, caches live prices in Redis,
rolls ticks up into one-minute candles, and serves them through a secured REST API and a live dashboard.
It runs as six Docker containers and is covered by about 400 automated tests.**

[![CI](https://github.com/siarkonyar/elt-dbt-phyton-data-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/siarkonyar/elt-dbt-phyton-data-pipeline/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.37-FF4B4B?logo=streamlit&logoColor=white)
![Docker](https://img.shields.io/badge/Docker_Compose-6_services-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-~400-success?logo=pytest&logoColor=white)
![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)

<br/>

[![Tech stack](https://skillicons.dev/icons?i=python,postgres,redis,fastapi,docker,githubactions&theme=light)](#-tech-stack)

</div>

---

## 📚 Contents

1. [What it does](#-what-it-does)
2. [Architecture](#-architecture)
3. [Tech stack](#-tech-stack)
4. [The life of one trade](#-the-life-of-one-trade)
5. [The services, one by one](#-the-services-one-by-one)
6. [Data model](#-data-model)
7. [Engineering decisions](#-engineering-decisions)
8. [Testing](#-testing)
9. [CI/CD pipeline](#-cicd-pipeline)
10. [Run it yourself](#-run-it-yourself)
11. [Configuration](#-configuration)
12. [Project structure](#-project-structure)
13. [Known limits and next steps](#-known-limits-and-next-steps)

---

## 🎯 What it does

| | |
|---|---|
| ⚡ **Extract** | Opens a WebSocket to [Finnhub](https://finnhub.io) and receives every trade for `AMZN`, `NVDA`, `GOOGL`, `TSLA` and `NFLX` as it happens. |
| 💾 **Load** | Writes the raw trades into PostgreSQL in small batches, once a second. Nothing is changed on the way in. |
| 🕯️ **Transform** | A separate service turns raw trades into **one-minute OHLCV candles** (open, high, low, close, volume). |
| 🟥 **Cache** | Keeps each symbol's latest price and day stats in **Redis**, so the dashboard can refresh every second without hitting the database. |
| 🔐 **Serve** | A **FastAPI** service with JWT login, user roles and price alerts. |
| 📊 **Show** | A **Streamlit** dashboard: live price cards, candlestick charts, price alerts and a pipeline health page. |
| 🔔 **Alert** | Users set "tell me when NVDA goes above $X". The stream checks every incoming trade against every open alert. |

> **Why "ELT" and not "ETL"?** Data is **E**xtracted and **L**oaded raw first. The **T**ransform step runs
> later, inside the warehouse, on data that is already stored. If the transform has a bug, you fix it and
> re-run it. The raw trades are never lost.

---

## 🏗 Architecture

Six containers on one Docker network. **PostgreSQL is the source of truth.** Redis is only a fast copy
that can be rebuilt from Postgres at any time.

```mermaid
flowchart LR
    FH["🌐 <b>Finnhub</b><br/>WebSocket + REST"]
    USER(["👤 Browser"])

    subgraph compose["🐳 Docker Compose · elt_network"]
        direction LR
        ST["⚡ <b>stream</b><br/>websocket-client<br/>threads + queue"]
        RD[("🟥 <b>Redis 7</b><br/>live price cache")]
        PG[("🐘 <b>PostgreSQL 13</b><br/>source of truth")]
        RU["🕯️ <b>rollup</b><br/>pandas"]
        API["🔐 <b>api</b><br/>FastAPI + JWT"]
        DASH["📊 <b>dashboard</b><br/>Streamlit + Plotly"]
    end

    FH -- "live trades" --> ST
    FH -. "market open?" .-> ST
    ST -- "insert batch every 1 s" --> PG
    ST -- "price:SYMBOL hashes" --> RD
    PG -- "last 10 min of trades" --> RU
    RU -- "upsert 1-min candles" --> PG
    RD -- "live board, every 1 s" --> DASH
    PG -- "candles, health, fallback" --> DASH
    DASH -- "login, alerts (REST)" --> API
    API -- "users, alerts, candles" --> PG
    USER -- ":8501" --> DASH
    USER -. ":8000/docs" .-> API

    classDef ext fill:#E0F2FE,stroke:#0284C7,color:#0C4A6E
    classDef svc fill:#EEF2FF,stroke:#4F46E5,color:#1E1B4B
    classDef store fill:#FEF3C7,stroke:#D97706,color:#78350F
    class FH,USER ext
    class ST,RU,API,DASH svc
    class RD,PG store
```

| Container | Kind | Runs | Port |
|---|---|---|---|
| `stream` | long-running worker | Finnhub WebSocket → Postgres + Redis, live alert checks | – |
| `rollup` | scheduled worker (every 60 s) | raw trades → one-minute candles | – |
| `api` | web service | FastAPI on Uvicorn | `8000` |
| `dashboard` | web app | Streamlit | `8501` |
| `destination_postgres` | database | PostgreSQL 13 with a named volume | `5434` |
| `redis` | cache | Redis 7, no persistence, localhost only | `6379` |

---

## 🧰 Tech stack

Every tool below is used for a specific job. The last column says why I picked it.

| Layer | Technology | What it does here | Why this choice |
|---|---|---|---|
| **Language** | ![Python](https://img.shields.io/badge/-Python_3.11-3776AB?logo=python&logoColor=white) | All four services, the tests, and CI helper scripts | One language end to end. Rich data and web libraries. |
| **Data source** | ![Finnhub](https://img.shields.io/badge/-Finnhub_API-1DB954) | WebSocket for live trades, REST for market open/closed status | Free real-time US equity trades over a WebSocket |
| **Streaming** | ![websocket-client](https://img.shields.io/badge/-websocket--client-555) `threading` `queue` | A socket thread receives trades; the main thread writes them | The socket never waits on the database, so a slow write can't drop trades |
| **Database** | ![PostgreSQL](https://img.shields.io/badge/-PostgreSQL_13-4169E1?logo=postgresql&logoColor=white) | Raw trades, candles, users, alerts, run logs | ACID transactions, `ON CONFLICT` upserts, exact `NUMERIC` prices, `DISTINCT ON` |
| **Cache** | ![Redis](https://img.shields.io/badge/-Redis_7-DC382D?logo=redis&logoColor=white) | One hash per symbol holding the live price and day stats | Reads in under a millisecond, so the board can refresh every second |
| **DB access** | ![SQLAlchemy](https://img.shields.io/badge/-SQLAlchemy_2.0-D71F00?logo=sqlalchemy&logoColor=white) + psycopg2 | Connection pooling, transactions, parameterised SQL | Plain SQL I can read and tune, with safe parameter binding (no SQL injection) |
| **Transform** | ![pandas](https://img.shields.io/badge/-pandas_2.2-150458?logo=pandas&logoColor=white) | Groups trades into OHLCV candles | A pure function that is very easy to unit test |
| **API** | ![FastAPI](https://img.shields.io/badge/-FastAPI-009688?logo=fastapi&logoColor=white) ![Pydantic](https://img.shields.io/badge/-Pydantic_v2-E92063?logo=pydantic&logoColor=white) ![Uvicorn](https://img.shields.io/badge/-Uvicorn-499848) | REST endpoints, request validation, auto-generated OpenAPI docs | Type-checked input, dependency injection that is easy to swap in tests |
| **Auth** | ![JWT](https://img.shields.io/badge/-PyJWT_HS256-000000?logo=jsonwebtokens&logoColor=white) ![bcrypt](https://img.shields.io/badge/-bcrypt-338) | Stateless login tokens, salted password hashes | Industry-standard and well-understood |
| **Frontend** | ![Streamlit](https://img.shields.io/badge/-Streamlit-FF4B4B?logo=streamlit&logoColor=white) ![Plotly](https://img.shields.io/badge/-Plotly-3F4F75?logo=plotly&logoColor=white) | Multi-page dashboard, candlestick charts, timed partial refreshes | A full interactive UI in pure Python |
| **Containers** | ![Docker](https://img.shields.io/badge/-Docker_Compose-2496ED?logo=docker&logoColor=white) | One image per service, health checks, start-up order | The whole system starts with one command |
| **Testing** | ![pytest](https://img.shields.io/badge/-pytest-0A9EDC?logo=pytest&logoColor=white) ![Testcontainers](https://img.shields.io/badge/-Testcontainers-291A3F) ![aiohttp](https://img.shields.io/badge/-aiohttp-2C5BB4?logo=aiohttp&logoColor=white) | Unit, integration and end-to-end tests; a fake Finnhub server | Tests the real containers, wired the same way as production |
| **Quality** | ![Ruff](https://img.shields.io/badge/-Ruff-D7FF64?logo=ruff&logoColor=black) ![coverage](https://img.shields.io/badge/-pytest--cov-555) | Linting, import sorting, coverage per service | Fast, and one tool replaces several |
| **CI** | ![GitHub Actions](https://img.shields.io/badge/-GitHub_Actions-2088FF?logo=githubactions&logoColor=white) | Lint → 4 parallel test lanes → end-to-end | A reusable workflow, real Postgres and Redis service containers |

---

## 🔄 The life of one trade

What happens in the roughly 60 seconds after someone buys an NVDA share:

```mermaid
sequenceDiagram
    autonumber
    participant FH as 🌐 Finnhub
    participant ST as ⚡ stream
    participant PG as 🐘 Postgres
    participant RD as 🟥 Redis
    participant RU as 🕯️ rollup
    participant DB as 📊 dashboard

    FH->>ST: trade message {s: NVDA, p: 104.0, v: 4, t: ...}
    Note over ST: parsed into a frozen Trade object<br/>and put on an in-memory queue
    ST->>PG: INSERT INTO raw_trades (within 1 s)
    ST->>RD: HSET price:NVDA price 104.0 day_high ...
    ST->>PG: any price alert crossed? mark it fired
    DB->>RD: HGETALL price:* (every 1 s)
    RD-->>DB: live price and day stats → price card
    RU->>PG: read the last 10 minutes of trades (every 60 s)
    Note over RU: group by symbol + minute<br/>first / max / min / last price
    RU->>PG: UPSERT INTO candles
    DB->>PG: read candles (cached 30 s)
    PG-->>DB: candlestick chart
```

---

## 🧩 The services, one by one

### ⚡ `stream`: the extract and load step

The stream has **two threads** that only talk through a queue. The socket thread does nothing slow.
It parses messages and puts trades on the queue. The main thread empties the queue once a second
and does all the I/O.

```mermaid
flowchart LR
    subgraph T1["🧵 Socket thread"]
        WS["Finnhub WebSocket"] --> P["parse_message()<br/><i>never raises</i>"]
    end
    P -- "Trade objects" --> Q[["queue.Queue"]]
    subgraph T2["🧵 Main thread: flush loop, every 1 s"]
        D["drain up to 500<br/><i>never blocks</i>"] --> W["Postgres<br/>insert + heartbeat"]
        W --> R["Redis<br/>live prices"]
        R --> A["check<br/>price alerts"]
    end
    Q --> D
```

**One flush, step by step.** The order matters: Redis is only updated **after** Postgres has
accepted the batch, so the cache never counts a trade that the database does not have.

```mermaid
sequenceDiagram
    participant F as Flush loop
    participant R as Redis
    participant P as Postgres

    F->>F: drain queue (≤ 500 trades)
    F->>R: read price:* hashes (1 pipeline)
    opt hash missing, or from an older day
        F->>P: seed day stats from raw_trades (1 query, all stale symbols)
    end
    F->>P: BEGIN · INSERT trades · UPDATE heartbeat · COMMIT
    alt insert worked
        F->>R: merge batch into each hash, HSET (1 pipeline)
    else insert failed
        F-->>F: log it, skip Redis, try again next second
    end
    F->>P: read pending alerts · mark crossed ones as fired
```

**Staying connected.** When the socket drops, the stream records why, waits, and reconnects. The wait
doubles each time (exponential backoff) with random jitter, so many clients don't all retry at the same moment.

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Connecting
    Connecting --> Streaming: open, subscribe to symbols
    Streaming --> Streaming: trades → queue → flush
    Streaming --> Backoff: socket closed or error
    Backoff --> Connecting: wait 1s, 2s, 4s … max 60s
    note right of Backoff
        reset to 1s after any
        successful message
    end note
```

Every connection is logged in `stream_sessions` with a heartbeat on each flush. This lets the dashboard
tell **"the market is quiet"** apart from **"the socket is dead"**.

### 🟥 Redis: the live price cache

Each symbol gets one Redis **hash**. Postgres is still the source of truth. This is a fast copy for the
dashboard, which reads it every second.

```text
redis> HGETALL price:NVDA
 day           2026-10-12
 trade_ts      2026-10-12T14:31:40+00:00
 price         104.0          ← latest trade
 volume        4.0
 day_open      100.0          ← first trade of the day
 day_high      108.0          ← max(old high, batch high)
 day_low       95.0           ← min(old low, batch low)
 trades_today  4              ← old count + batch size
```

How the dashboard reads it, and what happens when Redis is not there:

```mermaid
flowchart TD
    A["⏱️ Live board refresh, every 1 s"] --> B{"Redis has a hash<br/>for every symbol?"}
    B -- yes --> C{"hash.day == today?"}
    C -- yes --> OK["✅ price + day open/high/low"]
    C -- "no (yesterday's data)" --> STALE["⚠️ price only, day stats blank"]
    B -- "no · Redis down · 0.5 s timeout" --> FB["🐘 fall back to one SQL query<br/>on raw_trades"]
    FB --> OK2["✅ same board, a bit slower"]
```

| Design rule | Why |
|---|---|
| **No persistence** (`--save '' --appendonly no`) | Everything can be rebuilt from Postgres. A restart simply starts empty. |
| **0.5 s timeout** on every call | A slow Redis gives up in time and doesn't stall the 1-second flush |
| **One pipeline** per read or write | All five symbols in **one** network round trip |
| **Rebuild after any failure** | If a write fails, the next flush rebuilds day stats from Postgres instead of trusting a hash that may be behind |
| **Bound to `127.0.0.1`** | This Redis has no password, so it is never exposed to the network |

### 🕯️ `rollup`: the transform step

Every 60 seconds the rollup reads the **last 10 minutes** of trades and rebuilds those minutes' candles.
The window is wider than the interval on purpose: a late trade, or a missed run, is picked up next time.

**Worked example** (this exact case is checked by the end-to-end test):

| Time | Symbol | Price | Volume | |
|---|---|---|---|---|
| 14:31:10 | NVDA | **100.0** | 1 | ← first = **open** |
| 14:31:20 | NVDA | **108.0** | 2 | ← max = **high** |
| 14:31:30 | NVDA | **95.0** | 3 | ← min = **low** |
| 14:31:40 | NVDA | **104.0** | 4 | ← last = **close** |

```mermaid
flowchart LR
    T["4 raw trades<br/>NVDA, minute 14:31"] -- "sort by time<br/>group by symbol + minute" --> C["🕯️ 1 candle<br/>O 100 · H 108 · L 95 · C 104<br/>volume 10 · trades 4"]
```

The write is an **upsert** (`INSERT … ON CONFLICT (symbol, minute) DO UPDATE`), so running the same
minute twice gives exactly the same row. Every run is logged in `rollup_runs` with its status and row counts.

### 🔐 `api`: FastAPI

| Method | Path | Who can call it | What it does |
|---|---|---|---|
| `GET` | `/health` | anyone | Liveness check |
| `POST` | `/auth/register` | anyone | Creates a `user` account (`409` if the email exists) |
| `POST` | `/auth/login` | anyone | Checks the password, returns a JWT |
| `GET` | `/candles?symbol=NVDA&hours=1` | signed in | One-minute candles, 1–24 hours back |
| `POST` | `/alerts` | signed in | Creates a price alert owned by the caller |
| `GET` | `/alerts` | signed in | Users see **their own** alerts; admins see **all** |
| `DELETE` | `/alerts/{id}` | **admin only** | Deletes an alert (`403` for normal users) |

Interactive docs are generated automatically at **http://localhost:8000/docs**.

```mermaid
sequenceDiagram
    actor U as User
    participant D as 📊 dashboard
    participant A as 🔐 api
    participant P as 🐘 Postgres

    U->>D: email + password
    D->>A: POST /auth/login
    A->>P: find user by email
    A->>A: bcrypt.checkpw (12 rounds)
    A-->>D: JWT {sub: email, role, exp}
    Note over D: token kept in the user's<br/>Streamlit session only
    U->>D: "alert me when TSLA ≥ $250"
    D->>A: POST /alerts<br/>Authorization: Bearer token
    A->>A: verify signature + expiry → user + role
    A->>P: INSERT price_alerts (owner = token's user)
    A-->>D: 201 Created
```

**Security details**
- Passwords are hashed with **bcrypt** (salted, 12 rounds). The plain password is never stored.
- JWTs are **HS256**, and must contain `sub`, `role` and `exp`. The API **refuses to start** if `JWT_SECRET` is missing or shorter than 32 characters.
- Emails are trimmed and lower-cased before they are stored, so one person can't own two accounts that differ only in case.
- Input is validated by **Pydantic** models: email pattern, password length, `above`/`below` direction, a positive threshold.
- All SQL uses **bound parameters**. No string concatenation.
- No default admin password. The admin account is only created if you set **both** email and password.

### 📊 `dashboard`: Streamlit

| Page | What you see | Refresh |
|---|---|---|
| 📈 **Markets** | A price card per symbol (price, % change since open, sparkline) and a **Plotly candlestick chart** with 1h / 6h / 24h ranges | cards **1 s** (from Redis), chart **30 s** |
| 🔔 **Alerts** | Create alerts, see "Watching" and "Fired" counts, admins can delete | on action |
| 🛠️ **Pipeline** | A health strip *Finnhub → stream → raw_trades → rollup → candles → dashboard*, with ✅/⚠️ for each stage plus session and run logs | on load |

The dashboard uses `st.fragment(run_every=...)` so that only the part of the page that needs to change
is redrawn. The cards refresh every second; the heavier chart refreshes every 30 seconds. Closed-market
hours are cut out of the chart axis, so a 24-hour view isn't mostly empty space.

---

## 🗄 Data model

```mermaid
erDiagram
    users ||--o{ price_alerts : owns
    candles ||..|{ raw_trades : "built from"

    raw_trades {
        bigserial trade_id PK
        text symbol
        timestamptz trade_ts "indexed with symbol"
        numeric price
        numeric volume
        text conditions
        timestamptz received_at
    }
    candles {
        text symbol PK
        timestamptz minute PK
        numeric open
        numeric high
        numeric low
        numeric close
        numeric volume
        int trade_count
    }
    users {
        bigserial user_id PK
        text email UK
        text password_hash "bcrypt"
        text role "admin or user"
    }
    price_alerts {
        bigserial alert_id PK
        bigint user_id FK
        text symbol
        text direction "above or below"
        numeric threshold
        timestamptz triggered_at "null until fired"
        numeric triggered_price
    }
    stream_sessions {
        bigserial session_id PK
        timestamptz connected_at
        timestamptz last_message_at "heartbeat"
        bigint trades_received
        text status
    }
    rollup_runs {
        bigserial run_id PK
        timestamptz window_start
        timestamptz window_end
        bigint minutes_written
        text status
    }
```

Each service creates **its own tables** at start-up (`CREATE TABLE IF NOT EXISTS`). No service depends on
another one having started first. Prices are stored as `NUMERIC`, not `FLOAT`, so money values are exact.

---

## 🧠 Engineering decisions

These are the choices I would talk about in an interview.

| Decision | What it means in practice |
|---|---|
| **Idempotent writes** | Candle upserts and the Redis merge rules (max/min/keep-first) give the same result if they run twice. A crash and a re-run never double-count. |
| **Failure isolation** | Redis down? The board falls back to Postgres. Market-status API down? The stream keeps streaming. An alert check fails? Trades are still saved. One broken part never stops the others. |
| **One source of truth** | Postgres owns the data. Redis is updated **only after** a successful insert, and is rebuilt from Postgres whenever it might be wrong. |
| **Fail fast on bad config** | Every service validates its settings at start-up and exits with a clear message. The rollup even refuses a window shorter than its interval, because minutes would be silently skipped. |
| **Pure core, thin shell** | Candle building, alert matching, Redis merging, backoff and message parsing are pure functions with no database and no clock. That's why they're easy to unit test. |
| **Immutable data** | `Trade`, `ExponentialBackoff`, configs and users are `frozen` dataclasses. Functions return new values instead of changing old ones. |
| **Observable by design** | `stream_sessions` and `rollup_runs` record every connection and run, so the Pipeline page can show the health of each stage without reading container logs. |
| **One secret, one place** | One Postgres password in `.env`. Compose passes it to every service. Nothing to keep in sync. |

---

## 🧪 Testing

About **400 tests** across three tiers. Each tier tests something the tier below can't.

```mermaid
pie showData
    title Tests by tier
    "Unit · pure logic, no I/O" : 299
    "Integration · real Postgres + Redis" : 80
    "End-to-end · real containers" : 19
```

| Service | Unit | Integration | What's covered |
|---|---:|---:|---|
| `api` | 121 | 38 | routes, auth, tokens, passwords, validation, SQL queries |
| `stream` | 98 | 28 | parsing, buffering, backoff, alerts, Redis merge and round trip, day-stats SQL |
| `dashboard` | 49 | 3 | status rules, API client, Redis reader, candle SQL |
| `rollup` | 31 | 11 | candle maths, config validation, upsert idempotency |
| **e2e** | | **19** | the whole system, wired as in production |

**How the end-to-end test works.** It starts the **real Docker images** with Testcontainers. The real
Finnhub is swapped for a small fake WebSocket server written in `aiohttp`, which sends a known burst of trades.
The test then checks every hop:

```mermaid
flowchart LR
    FAKE["🎭 fake_websocket<br/>aiohttp"] -- "5 known trades" --> ST["stream"]
    ST --> PG[("Postgres")]
    ST --> RD[("Redis")]
    PG --> RU["rollup"] --> PG
    PG --> API["api"]
    TEST{{"🧪 pytest"}} -. "candle is exactly<br/>O100 H108 L95 C104" .-> PG
    TEST -. "live price hash written" .-> RD
    TEST -. "login, JWT, roles,<br/>alerts over HTTP" .-> API
    TEST -. "push a trade → alert fires live" .-> FAKE
```

Some test design choices:
- **Integration tests roll back.** Each test runs inside a transaction that is always rolled back, so no test can leak rows into another.
- **The e2e stack is isolated.** It uses its own Compose project name and random host ports, so your dev database is never touched.
- **Integration tests skip, not fail, when no database is running locally.** In CI, a pre-check makes the job **fail** if Postgres or Redis is unreachable, so a green job always means the tests really ran.

---

## 🚦 CI/CD pipeline

GitHub Actions runs on every push to `main`. After linting, the pipeline splits into **one lane per
container**. Each lane is the same reusable workflow (`service-tests.yml`). End-to-end runs only when all
four lanes pass.

```mermaid
flowchart LR
    PUSH(["🚀 push to main"]) --> LINT["🧹 ruff"]

    LINT --> AU["api<br/>unit"] --> AI["api<br/>integration"]
    LINT --> DU["dashboard<br/>unit"] --> DI["dashboard<br/>integration"]
    LINT --> RU["rollup<br/>unit"] --> RI["rollup<br/>integration"]
    LINT --> SU["stream<br/>unit"] --> SI["stream<br/>integration"]

    AI & DI & RI & SI --> E2E["🐳 e2e<br/>full compose stack"]

    classDef unit fill:#DCFCE7,stroke:#16A34A,color:#14532D
    classDef integ fill:#FEF9C3,stroke:#CA8A04,color:#713F12
    classDef e2e fill:#FCE7F3,stroke:#DB2777,color:#831843
    class AU,DU,RU,SU unit
    class AI,DI,RI,SI integ
    class E2E e2e
```

- **Integration jobs** get real `postgres:13` and `redis:7-alpine` **service containers**.
- Each job publishes **JUnit results** as a check, and writes a **coverage line** plus the 10 slowest tests to the job summary (`scripts/test_summary.py`).
- The lanes are separate jobs rather than a matrix, so each one shows up as its own box in the Actions graph.

---

## 🚀 Run it yourself

**You need:** Docker Desktop and a free API key from [finnhub.io](https://finnhub.io).

```bash
git clone https://github.com/siarkonyar/elt-dbt-phyton-data-pipeline.git
cd elt-dbt-phyton-data-pipeline
cp .env.example .env
```

Open `.env` and fill in these four values:

| Variable | What to put |
|---|---|
| `POSTGRES_PASSWORD` | any password |
| `FINNHUB_API_KEY` | your Finnhub key |
| `JWT_SECRET` | output of `openssl rand -hex 32` |
| `API_ADMIN_PASSWORD` | a password for the admin account (`admin@example.com`) |

Then start everything:

```bash
docker compose up --build
```

| Open | URL |
|---|---|
| 📊 Dashboard | http://localhost:8501 |
| 📘 API docs (Swagger) | http://localhost:8000/docs |
| 🐘 Postgres | `localhost:5434` · user `postgres` · db `destination_db` |
| 🟥 Redis | `localhost:6379` |

> 🕐 **Trades arrive mainly while the US market is open** (9:30–16:00 New York time, weekdays).
> Outside those hours the dashboard shows the last stored prices, and the Pipeline page shows when the last message arrived.

### Running the tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 1. Unit tests: no Docker needed
pytest tests/unit

# 2. Integration tests: need the compose Postgres + Redis and a test database
docker compose up -d destination_postgres redis
docker compose exec destination_postgres createdb -U postgres test_db
pytest tests/integration

# 3. End-to-end: builds and runs every image (takes a few minutes)
pytest -m e2e

# Lint
ruff check .
```

---

## ⚙️ Configuration

All settings come from environment variables (`.env`). Each service checks them at start-up.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `FINNHUB_API_KEY` | **required** | stream | Finnhub key |
| `POSTGRES_PASSWORD` | **required** | all | The one database password |
| `JWT_SECRET` | **required**, ≥ 32 chars | api | Signs login tokens |
| `STOCK_SYMBOLS` | `AMZN,NVDA,GOOGL,TSLA,NFLX` | stream | Symbols to subscribe to |
| `REDIS_URL` | `redis://redis:6379/0` | stream, dashboard | Live price cache |
| `FLUSH_INTERVAL_SECONDS` | `1` | stream | How often the queue is written |
| `FLUSH_MAX_ROWS` | `500` | stream | Max trades per flush |
| `RECONNECT_MIN_SECONDS` / `MAX` | `1` / `60` | stream | Reconnect backoff range |
| `STALE_AFTER_SECONDS` | `90` | stream, dashboard | Silence before the feed counts as stale |
| `ROLLUP_INTERVAL_SECONDS` | `60` | rollup | How often candles are rebuilt |
| `ROLLUP_WINDOW_MINUTES` | `10` | rollup | How far back each run looks |
| `JWT_EXPIRY_SECONDS` | `3600` | api | Token lifetime |
| `API_ADMIN_EMAIL` / `PASSWORD` | blank | api | Seed admin, created only if both are set |
| `API_BASE_URL` | `http://api:8000` | dashboard | Where the dashboard calls the api |
| `HISTORY_HOURS` | `24` | dashboard | Widest chart range |

---

## 🗂 Project structure

```text
elt/
├── stream/                  ⚡ Extract + Load: Finnhub → Postgres + Redis
│   ├── main.py              │  flush loop, reconnect loop, alert checks
│   ├── socket_client.py     │  WebSocket thread + message parsing
│   ├── live_prices.py       │  Redis hash merge, read, write
│   ├── alerts.py            │  which alerts a batch of trades crossed
│   ├── backoff.py           │  exponential backoff with jitter
│   ├── market_status.py     │  Finnhub REST: is the market open?
│   └── buffer.py · writer.py · db.py · config.py · schema.sql
├── rollup/                  🕯️ Transform: trades → 1-minute candles
│   ├── candles.py           │  pure pandas OHLCV aggregation
│   ├── writer.py            │  idempotent upsert + run log
│   └── main.py · db.py · config.py · schema.sql
├── api/                     🔐 FastAPI: auth, candles, alerts
│   ├── main.py              │  routes + start-up lifespan
│   ├── auth.py · tokens.py · passwords.py · emails.py
│   └── db.py · queries.py · serialize.py · config.py · schema.sql
├── dashboard/               📊 Streamlit
│   ├── app.py               │  sign-in + page navigation
│   ├── views/               │  markets.py · alerts.py · pipeline.py
│   ├── live_prices.py       │  Redis reader with Postgres fallback
│   └── data.py · queries.py · status.py · auth.py · ui.py
├── tests/
│   ├── unit/<service>/          🟢 pure logic
│   ├── integration/<service>/   🟡 real Postgres + Redis
│   └── e2e/                     🔴 real containers + fake Finnhub
├── .github/workflows/       🚦 ci.yml + reusable service-tests.yml
├── docs/superpowers/specs/  📝 design docs written before building
├── docker-compose.yaml
└── .env.example
```

---

## 🔭 Known limits and next steps

Honest notes on where this would need work at a larger scale:

- **Candle maths runs in pandas.** That's fine for five symbols and a 10-minute window. At hundreds of symbols the aggregation should move into a SQL `GROUP BY` inside Postgres.
- **The dashboard's symbol list is a constant** that has to match `STOCK_SYMBOLS` in the stream. A shared config would remove that manual step.
- **Redis has no password or TLS.** That's fine because it's bound to localhost. A cloud deployment would need both, or a managed Redis.
- **`raw_trades` grows forever.** Partitioning by day, or a retention job, would keep it bounded.

---

<div align="center">

Built by **[Siar Konyar](https://github.com/siarkonyar)** · Python · PostgreSQL · Redis · FastAPI · Streamlit · Docker · GitHub Actions

</div>
