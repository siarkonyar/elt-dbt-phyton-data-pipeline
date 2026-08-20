# **NO PREVIOUS COMMITS**

> # **There is no commit history here because I built this locally while experimenting. Everything is in the first commit.**

---

# Docker ELT + dbt

Small pipeline I put together to learn dbt. It copies data from one Postgres database into another, then transforms it with dbt. All of it runs in Docker.

The data is a made-up gym — trainers, members, classes, bookings.

## What's in it

- `source_postgres` — source database, seeded from `source_db_init/init.sql`
- `elt_script` — Python, dumps the source with `pg_dump` and restores it into the destination
- `destination_postgres` — where the data lands
- `dbt` — builds the models

On the dbt side there are four staging views, one per source table, then two marts: `fct_bookings` (each booking with the member, class and trainer names joined on) and `dim_attendance` (bookings per member plus an engagement label). 26 tests on top.

## Running it

You need Docker and a dbt profile at `~/.dbt/profiles.yml`:

```yaml
gym:
  target: dev
  outputs:
    dev:
      type: postgres
      host: destination_postgres
      port: 5432
      database: destination_db
      schema: public
      user: postgres
      password: secret
      threads: 1
```

The `destination_postgres` and `5432` matter. Those are the values from inside the Docker network — `localhost:5434` only works from your own machine, not from the dbt container.

Then:

```bash
cp elt_script/.env.example elt_script/.env
docker compose up -d
```

To poke at the results:

```bash
docker exec -it elt-destination_postgres-1 psql -U postgres -d destination_db
```

## dbt commands

```bash
docker compose run --rm --no-deps dbt build --profiles-dir /root --project-dir /dbt
```

Swap `build` for `run`, `test`, `ls` or `compile`. `build` does models and tests together and skips downstream models when a test fails.

## Notes

`depends_on` on its own only waits for a container to start, not to finish. `elt_script` exits after a few seconds, so dbt would happily run against an empty database. Fixed with:

```yaml
depends_on:
  elt_script:
    condition: service_completed_successfully
```

The dbt image (`ghcr.io/dbt-labs/dbt-postgres:1.4.7`) is old — dbt Labs stopped publishing it after 1.6. That's why `dbt_project.yml` needs explicit `config-version` and `version` keys. It's also amd64 only, so on Apple Silicon it runs emulated and Docker prints a warning. Harmless.

`profiles.yml` isn't in the repo, so cloning this alone isn't quite enough to run it.
