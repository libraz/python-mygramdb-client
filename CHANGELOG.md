# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `validate_identifier` and `escape_query_string` helpers in `command_utils`
- `ReplicationStatus.processed_events` and `ReplicationStatus.queue_size`
  fields, populated from the multi-line REPLICATION STATUS response
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

[Unreleased]: https://github.com/libraz/python-mygramdb-client/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/libraz/python-mygramdb-client/releases/tag/v1.0.0
