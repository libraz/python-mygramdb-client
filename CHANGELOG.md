# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/libraz/python-mygramdb-client/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/libraz/python-mygramdb-client/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/libraz/python-mygramdb-client/releases/tag/v1.0.0
