# Closed-loop E2E (docker-compose)

A self-contained end-to-end stack: **MySQL** (seeded with a fixed dataset) plus a
**MygramDB** server that replicates from it. It lets `tests/test_e2e.py` run against
a real server with deterministic data — nothing outside this directory is needed,
because the server is pulled as a published image.

## Run

```bash
# One shot: bring the stack up, run the e2e suite, tear it down.
tests/docker/run-e2e.sh
```

Equivalent manual steps:

```bash
docker compose -f tests/docker/docker-compose.yml up -d --wait
MYGRAM_E2E_SEEDED=1 pytest tests/test_e2e.py
docker compose -f tests/docker/docker-compose.yml down -v
```

## Knobs (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `MYGRAMDB_VERSION` | `1.7.0` | Server image tag (`ghcr.io/libraz/mygram-db:<tag>`; e.g. `1.7`, `latest`) |
| `MYSQL_VERSION` | `8.4` | MySQL image tag |
| `MYGRAM_PORT` | `11016` | Host port mapped to the server's TCP API |
| `MYGRAM_HTTP_PORT` | `18080` | Host port mapped to the server's HTTP/health API |
| `PYTHON` | `python` | Interpreter used to run pytest |
| `KEEP_UP` | `0` | When `1`, leave the stack running after tests (debugging) |

```bash
MYGRAMDB_VERSION=latest tests/docker/run-e2e.sh
KEEP_UP=1 tests/docker/run-e2e.sh     # inspect the running stack afterwards
```

## What it exercises

The fixed dataset (`mysql-init/02-seed.sql`) lets the suite assert exact results.
With `MYGRAM_E2E_SEEDED=1` the `TestSeededDataset` block in `tests/test_e2e.py`
checks, among others:

- database-qualified identity (`testdb.articles`) resolving to the seeded rows,
  and bare/qualified names resolving identically on a single-database server
- multi-word phrase quoting and `enabled = 1` required-filter visibility
- Japanese (ngram) matching
- `search_raw` boolean `OR`
- `facet` aggregation by category
- `search_with_highlights` snippet wrapping (server runs with `verify_text: all`)

The version-agnostic v1.7 round-trip checks (`search_raw`, `set_variable` /
`show_variables`, `sync` family) also run without the seed, against any server.

## Files

- `docker-compose.yml` — MySQL + MygramDB services
- `mygramdb.yaml` — server config (replicates `testdb` from the `mysql` service)
- `mysql-init/01-schema.sql` — schema + replication grants
- `mysql-init/02-seed.sql` — deterministic dataset
- `run-e2e.sh` — orchestrates up → test → down
