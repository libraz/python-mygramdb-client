# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-08-10

### Added

- MygramDB v1.10 protocol
  - Typed error frames: `ERROR` responses carry a numeric code, decoded into
    `ServerError.error_code` and into the specific subclasses
    `AuthenticationError` (permission denied), `ServerNotReadyError` (loading /
    not ready) and `ServerBusyError` (rate limited or table held). The full code
    table is exposed as `ErrorCode`, with `ServerError.is_transient` and
    `TRANSIENT_ERROR_CODES` for the states that can clear on their own. An
    untyped frame from an older server yields a plain `ServerError` with
    `error_code = None`
  - Administrative authentication: `ClientConfig.admin_token` issues `AUTH` on
    connect and on every transparent reconnect, so a reconnected session does
    not silently lose administrative access. `MygramClient.authenticate()`
    covers the ad-hoc case
  - Readiness over TCP: `ServerInfo.data_initialized` and `ServerInfo.ready`,
    read from `INFO`
  - Boolean query mode: `SearchOptions.query_mode = QueryMode.BOOLEAN` sends the
    query verbatim so the server parses `AND`/`OR`/`NOT` and grouping, while
    still applying filters, sorting, fuzzy matching and highlighting — the
    combination `search_raw()` cannot express
  - `ClientConfig.max_response_bytes` caps a single response frame; an
    overlong reply raises `ProtocolError` and drops the connection
- MygramDB v1.9 protocol
  - Facet pagination: `FacetOptions.offset`, and `FacetResponse.total_count`
    reporting the distinct value count before OFFSET and LIMIT
  - Comparison filters: `FilterCondition` / `FilterOp` (`=`, `!=`, `>`, `>=`,
    `<`, `<=`) via `filter_conditions` on `SearchOptions`, `CountOptions` and
    `FacetOptions`, alongside the existing equality `filters` dict
- `CacheStats` reports every counter `CACHE STATS` emits — lookup totals,
  invalidation index/queue memory, accounted memory, TTL expirations, the
  rejection and staleness breakdowns, invalidation modes, and the average
  hit/miss latencies with the total time saved. Fields an older server omits
  keep their defaults
- `DebugInfo` reports `cache_reason`, `cache_cost_ms`, `cache_key` and
  `highlight`, which the debug block already carried but the client dropped

### Fixed

- `facet()` no longer prefixes the search text with a `QUERY` token. No such
  keyword exists, so the server read it as part of the text and the aggregation
  was scoped to documents matching `QUERY <text>` rather than `<text>`
- `facet()` emits AND / NOT / FILTER refinements for a whole-table facet as
  well; they were silently dropped whenever `FacetOptions.query` was empty
- A literal query, term or filter value spelling a clause keyword (`AND`,
  `LIMIT`, `OR`, ...) or carrying a parenthesis or backslash is now quoted, so
  it matches as text instead of opening a clause or a boolean group
- `SearchOptions(sort_desc=False)` without a `sort_column` emits the
  `SORT ASC` shorthand; the ascending request was previously dropped and the
  server's descending primary-key default applied instead
- Identifiers (table, primary key, sort column, filter key) are rejected when
  they carry a `"`, `'` or `\`, which would flip the tokenizer's quote/escape
  state and swallow the rest of the command

### Changed

- `RetryPolicy.retryable` now also covers `ServerNotReadyError` and
  `ServerBusyError`, so a transient server state is retried from the server's
  numeric code rather than from a message-text match. Other server rejections
  remain non-retryable
- `command_timeout` is one deadline for the whole response instead of a timer
  restarted by each socket read; a server that trickles bytes can no longer hold
  a command open indefinitely
- `COUNT` responses are parsed strictly: a header that is not exactly
  `OK COUNT <decimal>` raises `ProtocolError` instead of reading a plausible
  number out of a frame that means something else
- `connect()` now performs the `AUTH` handshake under the command lock, and a
  rejected token closes the socket instead of leaving an unauthenticated
  connection that would fail on the first administrative command
- The docker-compose e2e stack targets MygramDB v1.10: it sets an admin token,
  narrows the CIDR allow list, and publishes its ports on loopback only — the
  previous configuration is rejected by v1.10's fail-closed validation

## [1.3.0] - 2026-07-10

### Added

- Connection pool (`MygramPool`) for high-throughput workloads
  - Fixed-ceiling pool multiplexing many concurrent requests over
    `min_connections`..`max_connections` connections, with FIFO wait fairness,
    validate-before-hand-out, and lifetime-based connection rotation
    (`PoolConfig`)
  - `pool.acquire()` async context manager yielding a checked-out
    `MygramClient` (`PooledConnection`), plus a read-only delegation API
    (`pool.search` / `search_raw` / `count` / `get` / `facet` / `info`)
  - `PoolStats` snapshot via `pool.stats()` (live/idle/in-use connections,
    cumulative acquire waits, discards, reconnects)
  - `pool.close()` promptly releases callers blocked in `acquire()` with
    `PoolClosedError` instead of leaving them waiting on a queue that will
    never be refilled
- Resilience primitives, opt-in via `PoolConfig`
  - `RetryPolicy` — exponential backoff with full jitter, applied to the pool's
    read-only delegation API; only transient failures (`TimeoutError`,
    `ConnectionError`) are retried by default
  - `CircuitBreakerConfig` — trips after `failure_threshold` consecutive
    connect/timeout failures and fails fast with `CircuitOpenError` for
    `reset_timeout` seconds before a half-open trial
  - Observability hook: `PoolConfig.on_event` receives `PoolEvent` notifications
    (acquire wait, connection discarded, retry, breaker state change)
- `ClientConfig` transport controls
  - `auto_reconnect` — transparently reconnect and resend a command when the
    socket is found dead *before* the request is written (a post-write drop is
    surfaced without resending, preserving non-idempotent command safety)
  - Separate `connect_timeout` / `command_timeout` (both fall back to `timeout`)
  - `tcp_keepalive` / `tcp_keepalive_idle` (enabled by default on TCP) to detect
    a silently dropped peer without waiting for the next read timeout
  - `socket_path` for Unix-domain-socket connections
- New exceptions: `PoolTimeoutError`, `PoolExhaustedError`, `PoolClosedError`,
  `CircuitOpenError`
- `py.typed` marker (PEP 561): the package now ships inline type information, so
  downstream type checkers use its annotations directly

### Changed

- `ConnectionError` and `TimeoutError` now also subclass the builtin
  `ConnectionError` / `TimeoutError` (which derive from `OSError`). Existing
  `except MygramError` handlers are unaffected, and callers can now also catch
  them as the builtins (or, on Python 3.11+, `TimeoutError` as
  `asyncio.TimeoutError`) without importing the library names
- MygramDB v1.8.0 protocol
  - `search_raw` / `search_raw_with_highlights` now send the boolean expression
    verbatim (unquoted) so the server's AST parser sees nested `AND` / `OR` /
    `NOT` / grouping. The previous single-quoted-token transport collapsed a
    grouped expression into one phrase; control characters are still rejected up
    front, so the unquoted send remains injection-safe
  - FACET responses preserve `#`-prefixed values (a leading `#` is only treated
    as a comment marker when the line carries no tab-separated count)
- `_read_response` now decodes the reply from an accumulated byte buffer,
  fixing a rare decode failure when a multi-byte UTF-8 sequence straddled a
  socket read boundary
- A command that fails mid-read (timeout or socket error) now tears its
  connection down, so the server's late response can never be read as the next
  command's reply. A read timeout consistently raises `TimeoutError` (rather
  than being reported as a `ConnectionError` on Python 3.9 / 3.10)

## [1.2.1] - 2026-06-15

### Fixed

- `_parse_leading_float` carried a duplicate `@staticmethod` decorator, which
  is uncallable on Python 3.9 (`'staticmethod' object is not callable`) and
  crashed debug-info parsing on SEARCH/COUNT with `DEBUG ON`. Python 3.10+ was
  unaffected. Removed the stray decorator

## [1.2.0] - 2026-06-15

### Added

- MygramDB v1.7 support
  - Database-qualified table identity (``database.table``) accepted by every
    table argument; new ``qualify_table_identity`` / ``parse_table_identity``
    helpers exported from the package
  - ``MygramClient.search_raw`` / ``search_raw_with_highlights`` for sending a
    pre-built boolean expression as a single quoted token (preserves
    ``OR`` / grouping semantics), with the new ``SearchRawOptions`` type
  - ``MygramClient.search_with_highlights`` convenience wrapper that enables
    the HIGHLIGHT clause with server defaults
  - ``MygramClient.set_variable`` / ``show_variables`` (MySQL-compatible
    ``SET`` / ``SHOW VARIABLES [LIKE ...]``)
  - ``MygramClient.sync`` / ``sync_status`` / ``sync_stop`` for on-demand
    table reloads
- ``quote_command_argument`` helper in ``command_utils`` mirroring the C++
  client's ``QuoteCommandArgumentIfNeeded``
- Self-contained docker-compose e2e harness under ``tests/docker/`` with a
  ``run-e2e.sh`` orchestrator and a deterministic seeded dataset
- Unit tests for the v1.7 surface and seeded/round-trip e2e tests

### Changed

- DUMP filepaths (``dump_save`` / ``dump_load`` / ``dump_verify`` /
  ``dump_info``) are now quoted via ``quote_command_argument`` when they
  contain whitespace instead of being sent as split tokens
- ``_is_response_complete`` recognises ``OK SYNC_STATUS`` as an
  ``END``-terminated multi-line response (including the server's trailing
  blank line after ``END``)

### Fixed

- ``_parse_debug_info`` now tolerates the unit suffix the server appends to
  debug timings (e.g. ``query_time: 0.011ms``). Previously ``float()`` raised
  ``ValueError``, which surfaced as a crash on SEARCH debug parsing and a
  silently dropped ``debug`` on COUNT

## [1.1.1] - 2026-05-09

### Added

- `validate_identifier` and `escape_query_string` helpers in `command_utils`
- `ReplicationStatus.processed_events` and `ReplicationStatus.queue_size`
  fields, populated from the multi-line REPLICATION STATUS response
- `MAX_HIGHLIGHT_TAG_BYTES` (256) cap on `HighlightOptions.open_tag` and
  `close_tag`, mirroring the server-side `kMaxHighlightTagLength` limit
  introduced in MygramDB v1.6.1 to prevent response-size amplification
- 44 new unit tests covering identifier validation, query escaping,
  OFFSET-only emission, OR-only/parenthesized expression simplification,
  REPLICATION extra fields, response-completeness detection, and
  concurrent `send_command` serialization

### Changed

- `MygramClient.search` / `count` / `get` / `facet` now reject identifiers
  (table, primary key, sort column, filter keys) that contain whitespace
  or control characters; previously such values would corrupt the
  protocol stream by splitting a single token into multiple tokens
- Free-form values on the wire (query, AND/NOT terms, FILTER values) are
  now quoted via `escape_query_string`. Empty queries are emitted as the
  explicit `""` token so the server sees a well-formed command instead
  of a malformed one with collapsed whitespace
- `SearchOptions.offset > 0` with `limit == 0` now emits a bare
  `OFFSET <n>` clause; previously the offset was silently dropped
- `validate_highlight` now rejects `open_tag` / `close_tag` values whose
  UTF-8 encoding exceeds 256 bytes, matching the server cap
- `MygramClient.send_command` is now serialized via an internal
  `asyncio.Lock`, so concurrent calls on the same client no longer
  interleave bytes on the wire
- `_is_response_complete` matches `OK INFO`, `OK REPLICATION`,
  `OK CACHE_STATS`, `OK DUMP_STATUS` and `OK DUMP_INFO` against the
  first line only (instead of an `in buffer` substring check) and
  recognises `OK DUMP_INFO` as an `END\r\n`-terminated response. The
  previous loose substring match could cause both false positives and
  hung reads when the prefix appeared in payload content

### Fixed

- `simplify_search_expression` no longer flattens OR-only or
  parenthesized expressions like `python OR ruby` and `(a OR b)` into an
  AND interpretation; the OR sub-expression is now surfaced as a single
  parenthesized `main_term`
- `_parse_replication_status_response` accepts both `current_gtid:` and
  `gtid:` keys in multi-line responses

## [1.1.0] - 2026-04-15

### Added

- MygramDB v1.6 support
  - `SearchOptions.fuzzy` for Levenshtein fuzzy search (edit distance 1 or 2)
  - `SearchOptions.highlight` (`HighlightOptions`) for HIGHLIGHT clause with
    customizable open/close tags, snippet length and max fragments
  - `SearchResult.snippet` field returned when highlighting is enabled
  - `MygramClient.facet()` for FACET aggregation with optional query scoping
    (`FacetOptions`, `FacetValue`, `FacetResponse`)
  - BM25 relevance scoring via the special `_score` sort column
- New validators in `command_utils`: `validate_fuzzy`, `validate_highlight`,
  `validate_facet_column`
- 68 new unit tests covering the v1.6 surface

### Changed

- `_parse_search_response` now handles the multi-line HIGHLIGHT response
  format in addition to the classic single-line format
- Internal response framing recognises the FACET and HIGHLIGHT multi-line
  response terminators

## [1.0.0] - 2025-12-13

### Added

- Initial release
- TCP socket communication with MygramDB (asyncio-based)
- Full-text search operations (search, count, get)
- Search expression parser with web-style syntax
- INFO, CONFIG, REPLICATION, DUMP, CACHE, OPTIMIZE commands
- Input validation and error handling
- Full type hints with dataclasses

[Unreleased]: https://github.com/libraz/python-mygramdb-client/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/libraz/python-mygramdb-client/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/libraz/python-mygramdb-client/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/libraz/python-mygramdb-client/releases/tag/v1.0.0
