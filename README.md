# python-mygramdb-client

[![CI](https://img.shields.io/github/actions/workflow/status/libraz/python-mygramdb-client/ci.yml?branch=main&label=CI)](https://github.com/libraz/python-mygramdb-client/actions)
[![PyPI](https://img.shields.io/pypi/v/mygramdb-client)](https://pypi.org/project/mygramdb-client/)
[![codecov](https://codecov.io/gh/libraz/python-mygramdb-client/branch/main/graph/badge.svg)](https://codecov.io/gh/libraz/python-mygramdb-client)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.9-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](https://github.com/libraz/python-mygramdb-client)

Python client library for [MygramDB](https://github.com/libraz/mygram-db/) — a high-performance in-memory full-text search engine with MySQL replication support.

> Compatible with **MygramDB v1.8** (verbatim boolean transport, FACET `#`-value
> preservation). v1.7 (multi-database, `search_raw`, runtime variables, on-demand
> sync) and v1.6 (fuzzy search, highlight, facets, BM25) remain supported.

## Overview

MygramDB provides **25-200x faster** full-text search than MySQL FULLTEXT. This client communicates via MygramDB's TCP text protocol (memcached-style) with zero external dependencies.

| | MySQL FULLTEXT | MygramDB |
|---|---|---|
| **Search Speed** | Baseline | 25-200x faster |
| **Storage** | On-disk | In-memory |
| **Replication** | — | MySQL binlog |
| **Protocol** | MySQL | TCP (memcached-style) |

### Features

- **Zero Dependencies** — Standard library only
- **Async/Await API** — Modern asyncio-based interface with context manager support
- **Connection Pooling** — Built-in `MygramPool` for high-throughput workloads, with per-command retry, circuit breaker, and observability hooks
- **Resilient Transport** — Auto-reconnect, separate connect/command timeouts, and TCP keepalive
- **Search Expression Parser** — Web-style search syntax (+required, -excluded, "phrase", OR, grouping)
- **Full Protocol Support** — All MygramDB commands (SEARCH, COUNT, GET, INFO, CACHE, DUMP, OPTIMIZE, etc.)
- **Type Safety** — Full type hints with dataclasses, shipped with a PEP 561 `py.typed` marker
- **Input Validation** — Built-in protection against control character injection

## Installation

```bash
pip install mygramdb-client
```

### From source

```bash
git clone https://github.com/libraz/python-mygramdb-client.git
cd python-mygramdb-client
rye sync
```

## Quick Start

```python
import asyncio
from mygramdb_client import MygramClient, ClientConfig, SearchOptions

async def main():
    async with MygramClient(ClientConfig(host='localhost', port=11016)) as client:
        # Search
        results = await client.search('articles', 'hello', SearchOptions(limit=100))
        print(f"Found {results.total_count} results")

        # Count
        count = await client.count('articles', 'technology')
        print(f"Count: {count.count}")

        # Get document by ID
        doc = await client.get('articles', '12345')
        print(f"Doc: {doc.primary_key} {doc.fields}")

asyncio.run(main())
```

## Search Expressions

Parse web-style search queries into structured search parameters:

```python
from mygramdb_client import simplify_search_expression

# Space = AND, - = NOT, "" = phrase, OR = OR, () = grouping
expr = simplify_search_expression('hello world -spam')
# expr = SimplifiedExpression(main_term='hello', and_terms=['world'], not_terms=['spam'])

results = await client.search('articles', expr.main_term, SearchOptions(
    and_terms=expr.and_terms,
    not_terms=expr.not_terms,
    limit=100,
    offset=50,
    filters={'status': 'published', 'lang': 'en'},
    sort_column='created_at',
    sort_desc=True,
))
```

## MygramDB v1.6 Features

```python
from mygramdb_client import HighlightOptions, FacetOptions, SearchOptions

# BM25 relevance scoring
result = await client.search('articles', 'python',
    SearchOptions(sort_column='_score', sort_desc=True))

# Fuzzy search (Levenshtein distance 1 or 2)
result = await client.search('articles', 'helo',
    SearchOptions(fuzzy=1))

# Highlighted snippets
result = await client.search('articles', 'python',
    SearchOptions(highlight=HighlightOptions(
        open_tag='<mark>', close_tag='</mark>',
        snippet_len=150, max_fragments=3,
    )))
for r in result.results:
    print(r.primary_key, r.snippet)

# Facet aggregation
facets = await client.facet('articles', 'category',
    FacetOptions(query='python', limit=10))
for v in facets.results:
    print(f'{v.value}: {v.count}')
```

## MygramDB v1.7 Features

### Multi-database (qualified table identity)

A v1.7+ instance can index tables from more than one database. Reference a
table as `database.table`; bare names still work on single-database servers.

```python
from mygramdb_client import qualify_table_identity, parse_table_identity

await client.search('app_db.articles', 'hello')

qualify_table_identity('articles', 'app_db')  # 'app_db.articles'
parse_table_identity('app_db.articles')       # ('app_db', 'articles')
```

### Boolean search

`search()` sends the query as a single (auto-quoted) token. For boolean
`AND`/`OR`/`NOT`/grouping, build the expression and pass it to `search_raw()`,
which sends it verbatim (unquoted, MygramDB v1.8+) so the server's AST parser
sees the nested structure:

```python
from mygramdb_client import convert_search_expression, SearchRawOptions

raw = convert_search_expression('python OR (ruby AND rails)')
res = await client.search_raw('articles', raw, SearchRawOptions(limit=50))

# search_with_highlights / search_raw_with_highlights enable the HIGHLIGHT clause:
res = await client.search_with_highlights('articles', 'python')
```

### Runtime variables and on-demand sync

```python
await client.set_variable('logging.level', 'info')
print(await client.show_variables('logging%'))

await client.sync('app_db.articles')
print(await client.sync_status())
await client.sync_stop('app_db.articles')
```

## MygramDB v1.8 Features

v1.8 refines two wire-protocol behaviors used by the client:

- **Verbatim boolean transport** — `search_raw()` sends its expression unquoted,
  so the server parses `AND`/`OR`/`NOT` and grouping, including OR groups nested
  under AND. Control characters are still rejected before send.
- **FACET `#`-value preservation** — a `facet()` value that starts with `#` is
  kept; only tab-less `#` lines in the FACET response are treated as comments.

```python
# Boolean expression parsed by the server (unquoted transport)
raw = convert_search_expression('python OR (ruby AND rails)')
res = await client.search_raw('articles', raw, SearchRawOptions(limit=50))

# '#hashtag'-style facet values are retained
facets = await client.facet('articles', 'tags')
```

## High-throughput: Connection Pooling

For hundreds of requests per second, use `MygramPool` instead of a single
connection. It multiplexes concurrent requests over a bounded set of
connections and layers on retry, a circuit breaker, and event hooks.

```python
from mygramdb_client import (
    MygramPool, PoolConfig, ClientConfig,
    RetryPolicy, CircuitBreakerConfig,
)

pool_config = PoolConfig(
    min_connections=4,
    max_connections=32,
    acquire_timeout=2.0,
    retry_policy=RetryPolicy(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, reset_timeout=10.0),
)

async with MygramPool(ClientConfig(host='localhost'), pool_config) as pool:
    # Delegation API: acquire, run, release — with retry + breaker applied
    result = await pool.search('articles', 'hello')

    # Or check out a connection explicitly
    async with pool.acquire() as client:
        await client.count('articles', 'python')

    print(pool.stats())  # PoolStats snapshot
```

See [docs/en/advanced-usage.md](docs/en/advanced-usage.md) for timeouts,
auto-reconnect, and observability details.

## Type Hints

The package ships a PEP 561 `py.typed` marker, so type checkers (mypy, pyright)
use its inline annotations directly — no stub package needed. Full type
definitions are included:

```python
from mygramdb_client import (
    ClientConfig,
    SearchResponse,
    CountResponse,
    Document,
    ServerInfo,
    SearchOptions,
    DumpStatus,
    CacheStats,
)
```

## Development

```bash
rye sync              # Install dependencies
rye run pytest        # Run tests
rye run pytest -v     # Run tests (verbose)
rye run flake8 src tests  # Lint
```

## License

[MIT](LICENSE)
