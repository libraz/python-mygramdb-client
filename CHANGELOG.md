# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.1.0]: https://github.com/libraz/python-mygramdb-client/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/libraz/python-mygramdb-client/releases/tag/v1.0.0
