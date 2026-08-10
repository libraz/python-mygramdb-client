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
| `MYGRAMDB_VERSION` | `1.10.0` | Server image tag (`ghcr.io/libraz/mygram-db:<tag>`; e.g. `1.8.0`, `latest`) |
| `MYSQL_VERSION` | `8.4` | MySQL image tag |
| `MYGRAM_PORT` | `11016` | Host port mapped to the server's TCP API |
| `MYGRAM_HTTP_PORT` | `18080` | Host port mapped to the server's HTTP/health API |
| `MYGRAM_ADMIN_TOKEN` | `e2e_admin_token` | Administrative token given to the server and, when it supports `AUTH`, to the client |
| `PYTHON` | `python` | Interpreter used to run pytest |
| `KEEP_UP` | `0` | When `1`, leave the stack running after tests (debugging) |

```bash
MYGRAMDB_VERSION=1.8.0 tests/docker/run-e2e.sh   # older server, same suite
KEEP_UP=1 tests/docker/run-e2e.sh                # inspect the running stack afterwards
```

## Administrative authentication

The server's TCP listener binds `0.0.0.0` so the host can reach it, and v1.10
refuses to start in that shape unless `api.admin_token` is configured. The token
is injected through `MYGRAM_API_ADMIN_TOKEN`, which the server reads ahead of the
mounted `mygramdb.yaml`, so one config file serves every image the suite runs
against — an older server simply ignores the variable.

`run-e2e.sh` then reads the running server's version from `GET /info` and hands
the client a token only when that version is at least 1.10.0. The tag alone is
not enough to decide, since it can be a moving alias such as `latest`, and a
server predating `AUTH` rejects the command outright. Against v1.10 this means
the suite's administrative calls — `CACHE STATS`, `DUMP STATUS`, `OPTIMIZE`,
`SET`, `SHOW VARIABLES` and the `SYNC` family — exercise the authenticated path
on every connect, pooled connections included.

## What it exercises

The fixed dataset (`mysql-init/02-seed.sql`) lets the suite assert exact results.
With `MYGRAM_E2E_SEEDED=1` the `TestSeededDataset` block in `tests/test_e2e.py`
checks, among others:

- database-qualified identity (`testdb.articles`) resolving to the seeded rows,
  and bare/qualified names resolving identically on a single-database server
- multi-word phrase quoting and `enabled = 1` required-filter visibility
- Japanese (ngram) matching
- `search_raw` boolean `OR`, including an `OR` group nested under `AND`
  (unquoted boolean transport, MygramDB v1.8+)
- `facet` aggregation by category
- `search_with_highlights` snippet wrapping (server runs with `verify_text: all`)
- `MygramPool` delegation and concurrent round-trips against the live server

Two further blocks cover the surface a specific server version introduced, and
skip against anything older — the gate reads the version from `INFO` rather than
the image tag, so a moving alias resolves correctly:

- `TestQuerySurfaceV19`: `boolean` query mode including a nested group and a mode
  combined with a filter, literal mode treating `OR` as text, the comparison
  filter operators through both `filters` and `filter_conditions`, facet
  pagination with its distinct-value total, and ascending primary-key order
- `TestProtocolSurfaceV110` / `TestAdministrativeAuthentication`: readiness on
  `INFO`, a typed `ServerError` code for an unknown table, and — when a token is
  configured — that search needs none, that an administrative command without one
  is refused with the authentication code, that `authenticate()` upgrades an open
  connection, that a wrong token fails the connect outright, and that a pooled
  connection can run an administrative command

The version-agnostic round-trip checks (`search_raw`, `set_variable` /
`show_variables`, `sync` family) also run without the seed, against any server.

## Files

- `docker-compose.yml` — MySQL + MygramDB services
- `mygramdb.yaml` — server config (replicates `testdb` from the `mysql` service)
- `mysql-init/01-schema.sql` — schema + replication grants
- `mysql-init/02-seed.sql` — deterministic dataset
- `run-e2e.sh` — orchestrates up → test → down
