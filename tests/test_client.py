"""Tests for MygramClient."""
import asyncio

import pytest

from mygramdb_client import (
    CacheStats,
    ClientConfig,
    CountResponse,
    DebugInfo,
    Document,
    DumpStatus,
    MygramClient,
    ReplicationStatus,
    SearchResponse,
    ServerInfo,
)
from mygramdb_client.errors import ErrorCode, ProtocolError


class TestClientConfig:
    """Tests for ClientConfig defaults."""

    def test_default_values(self):
        config = ClientConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 11016
        assert config.timeout == 5.0
        assert config.recv_buffer_size == 65536
        assert config.max_query_length == 128

    def test_custom_values(self):
        config = ClientConfig(
            host="localhost",
            port=12345,
            timeout=10.0,
            recv_buffer_size=1024,
            max_query_length=256,
        )
        assert config.host == "localhost"
        assert config.port == 12345
        assert config.timeout == 10.0
        assert config.recv_buffer_size == 1024
        assert config.max_query_length == 256

    def test_socket_path_default(self):
        config = ClientConfig()
        assert config.socket_path == ""

    def test_socket_path_custom(self):
        config = ClientConfig(socket_path="/tmp/mygramdb.sock")
        assert config.socket_path == "/tmp/mygramdb.sock"


class TestSearchResponseParsing:
    """Tests for search response parsing."""

    def test_parse_basic_search_response(self):
        response = "OK RESULTS 3 id1 id2 id3"
        result = MygramClient._parse_search_response(response)

        assert isinstance(result, SearchResponse)
        assert result.total_count == 3
        assert len(result.results) == 3
        assert result.results[0].primary_key == "id1"
        assert result.results[1].primary_key == "id2"
        assert result.results[2].primary_key == "id3"
        assert result.debug is None

    def test_parse_empty_search_response(self):
        response = "OK RESULTS 0"
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 0
        assert len(result.results) == 0

    def test_parse_search_response_with_debug(self):
        response = """OK RESULTS 1 id1
# DEBUG
query_time: 1.5
terms: 2
candidates: 100
final: 1"""
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 1
        assert result.debug is not None
        assert result.debug.query_time_ms == 1.5
        assert result.debug.terms == 2
        assert result.debug.candidates == 100
        assert result.debug.final == 1

    def test_parse_invalid_search_response_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid SEARCH response"):
            MygramClient._parse_search_response("INVALID")


class TestHighlightSearchResponseParsing:
    """A highlighted result set is one tab-separated row per document."""

    def test_parse_multiline_highlight_response(self):
        response = (
            "OK RESULTS 2\n"
            "id1\tHello <em>world</em>\n"
            "id2\tGoodbye <em>world</em>"
        )
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 2
        assert len(result.results) == 2
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == "Hello <em>world</em>"
        assert result.results[1].primary_key == "id2"
        assert result.results[1].snippet == "Goodbye <em>world</em>"

    def test_parse_highlight_with_empty_snippet(self):
        result = MygramClient._parse_search_response("OK RESULTS 1\nid1\t")

        assert result.total_count == 1
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == ""

    def test_parse_highlight_without_tab_treated_as_pk(self):
        """A payload line without a tab should be treated as a bare PK."""
        result = MygramClient._parse_search_response("OK RESULTS 1\nid1")

        assert result.total_count == 1
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == ""

    def test_classic_single_line_still_works(self):
        """Regression test: classic SEARCH response must still parse."""
        result = MygramClient._parse_search_response("OK RESULTS 3 id1 id2 id3")

        assert result.total_count == 3
        assert len(result.results) == 3
        assert [r.primary_key for r in result.results] == ["id1", "id2", "id3"]
        assert all(r.snippet is None for r in result.results)

    def test_highlight_with_debug_block(self):
        response = (
            "OK RESULTS 1\n"
            "id1\tmatched <em>x</em>\n"
            "# DEBUG\n"
            "query_time: 1.5\n"
            "terms: 2"
        )
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 1
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == "matched <em>x</em>"
        assert result.debug is not None
        assert result.debug.query_time_ms == 1.5

    def test_debug_block_tolerates_ms_unit_suffix(self):
        # The server emits timings with a trailing unit (e.g. "0.011ms").
        response = (
            "OK RESULTS 1\n"
            "id1\tmatched <em>x</em>\n"
            "# DEBUG\n"
            "query_time: 0.011ms\n"
            "index_time: 1.250ms\n"
            "filter_time: 0.5ms\n"
            "terms: 2"
        )
        result = MygramClient._parse_search_response(response)

        assert result.debug is not None
        assert result.debug.query_time_ms == 0.011
        assert result.debug.index_time_ms == 1.25
        assert result.debug.filter_time_ms == 0.5


class TestCountResponseParsing:
    """Tests for count response parsing."""

    def test_parse_basic_count_response(self):
        response = "OK COUNT 42"
        result = MygramClient._parse_count_response(response)

        assert isinstance(result, CountResponse)
        assert result.count == 42
        assert result.debug is None

    def test_parse_count_response_with_debug(self):
        response = """OK COUNT 42
# DEBUG
query_time: 0.5
terms: 1"""
        result = MygramClient._parse_count_response(response)

        assert result.count == 42
        assert result.debug is not None
        assert result.debug.query_time_ms == 0.5

    def test_parse_invalid_count_response_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid COUNT response"):
            MygramClient._parse_count_response("INVALID")

    def test_trailing_token_is_rejected(self):
        # Strict header parsing (v1.10+): anything but "OK COUNT <decimal>" is
        # a different frame, not a count to be read out of it.
        with pytest.raises(ProtocolError, match="Invalid COUNT response"):
            MygramClient._parse_count_response("OK COUNT 42 extra")

    def test_non_numeric_count_is_rejected(self):
        with pytest.raises(ProtocolError, match="Invalid COUNT response"):
            MygramClient._parse_count_response("OK COUNT many")

    def test_debug_block_is_still_parsed(self):
        response = "OK COUNT 42\n\n# DEBUG\nquery_time: 1.5ms"
        result = MygramClient._parse_count_response(response)

        assert result.count == 42
        assert result.debug is not None
        assert result.debug.query_time_ms == 1.5


class TestDocumentResponseParsing:
    """Tests for document response parsing."""

    def test_parse_basic_document_response(self):
        response = "OK DOC 12345 title=Hello author=John"
        result = MygramClient._parse_document_response(response)

        assert isinstance(result, Document)
        assert result.primary_key == "12345"
        assert result.fields["title"] == "Hello"
        assert result.fields["author"] == "John"

    def test_parse_document_response_no_fields(self):
        response = "OK DOC 12345"
        result = MygramClient._parse_document_response(response)

        assert result.primary_key == "12345"
        assert result.fields == {}

    def test_parse_invalid_document_response_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid GET response"):
            MygramClient._parse_document_response("INVALID")


class TestInfoResponseParsing:
    """Tests for info response parsing."""

    def test_parse_info_response(self):
        response = """OK INFO
version: 1.0.0
uptime_seconds: 3600
total_requests: 1000
connected_clients: 5
used_memory_bytes: 1048576
total_documents: 500
tables: articles, users"""
        result = MygramClient._parse_info_response(response)

        assert isinstance(result, ServerInfo)
        assert result.version == "1.0.0"
        assert result.uptime_seconds == 3600
        assert result.total_requests == 1000
        assert result.active_connections == 5
        assert result.index_size_bytes == 1048576
        assert result.doc_count == 500
        assert result.tables == ["articles", "users"]

    def test_parse_invalid_info_response_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid INFO response"):
            MygramClient._parse_info_response("INVALID")

    def test_info_reports_data_initialized_and_readiness(self):
        # Readiness over TCP (v1.10+).
        response = (
            "OK INFO\n"
            "version: 1.10.0\n"
            "data_initialized: true\n"
            "readiness: ready\n"
            "END"
        )
        info = MygramClient._parse_info_response(response)

        assert info.data_initialized is True
        assert info.ready is True

    def test_not_ready_is_reported(self):
        response = (
            "OK INFO\n"
            "data_initialized: false\n"
            "readiness: not_ready\n"
            "END"
        )
        info = MygramClient._parse_info_response(response)

        assert info.data_initialized is False
        assert info.ready is False

    def test_older_server_without_the_fields_reports_not_ready(self):
        info = MygramClient._parse_info_response("OK INFO\nversion: 1.8.0\nEND")

        assert info.data_initialized is False
        assert info.ready is False


class TestReplicationStatusParsing:
    """Tests for replication status response parsing."""

    def test_parse_single_line_replication_status(self):
        response = "OK REPLICATION status=running gtid=abc123"
        result = MygramClient._parse_replication_status_response(response)

        assert isinstance(result, ReplicationStatus)
        assert result.running is True
        assert result.gtid == "abc123"

    def test_parse_multi_line_replication_status(self):
        response = """OK REPLICATION
status: running
current_gtid: xyz789
processed_events: 100
END"""
        result = MygramClient._parse_replication_status_response(response)

        assert result.running is True
        assert result.gtid == "xyz789"

    def test_parse_stopped_replication_status(self):
        response = "OK REPLICATION status=stopped gtid="
        result = MygramClient._parse_replication_status_response(response)

        assert result.running is False

    def test_parse_invalid_replication_response_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid REPLICATION"):
            MygramClient._parse_replication_status_response("INVALID")

    def test_parse_v110_diagnostics_fields(self):
        response = """OK REPLICATION
status: running
current_gtid: xyz789
processed_events: 100
queue_size: 2
crc_errors: 3
schema_incompatible: false
last_error_code: 0
last_error:
last_applied_unixtime: 1770000000
seconds_since_last_applied: 4
END"""
        result = MygramClient._parse_replication_status_response(response)

        assert result.state == "running"
        assert result.crc_errors == 3
        assert result.schema_incompatible is False
        assert result.last_error_code == 0
        assert result.last_error == ""
        assert result.last_applied_unixtime == 1770000000
        assert result.seconds_since_last_applied == 4

    def test_state_separates_a_failure_from_a_requested_stop(self):
        # `running` reads False for both, so only `state` tells them apart.
        stopped = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: stopped\nEND"
        )
        failed = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: failed\nlast_error_code: 2007\n"
            "last_error: binlog read failed\nEND"
        )

        assert stopped.running is False
        assert failed.running is False
        assert stopped.state == "stopped"
        assert failed.state == "failed"
        assert failed.last_error_code == ErrorCode.MYSQL_REPLICATION_ERROR
        assert failed.last_error == "binlog read failed"

    def test_unrecognized_state_is_passed_through(self):
        # A state a future server adds stays visible rather than being dropped.
        result = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: catching_up\nEND"
        )

        assert result.state == "catching_up"
        assert result.running is False

    def test_schema_incompatible_is_read_as_a_boolean(self):
        result = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: failed\nschema_incompatible: true\nEND"
        )

        assert result.schema_incompatible is True

    def test_negative_lag_sentinel_is_passed_through(self):
        # -1 means "no event applied yet", which must not read as a lag of zero.
        result = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: running\n"
            "last_applied_unixtime: 0\nseconds_since_last_applied: -1\nEND"
        )

        assert result.seconds_since_last_applied == -1
        assert result.last_applied_unixtime == 0

    def test_diagnostics_default_when_the_server_omits_them(self):
        # A pre-v1.10 server reports none of these keys.
        result = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: running\ncurrent_gtid: abc\nEND"
        )

        assert result.crc_errors == 0
        assert result.schema_incompatible is False
        assert result.last_error_code == 0
        assert result.last_error == ""
        assert result.last_applied_unixtime == 0
        # None, not 0: an absent field must not read as a lag of zero.
        assert result.seconds_since_last_applied is None

    def test_single_line_response_reports_no_state(self):
        result = MygramClient._parse_replication_status_response(
            "OK REPLICATION status=running gtid=abc123"
        )

        assert result.state == ""
        assert result.seconds_since_last_applied is None

    def test_malformed_numeric_diagnostics_keep_their_default(self):
        result = MygramClient._parse_replication_status_response(
            "OK REPLICATION\nstatus: running\ncrc_errors: n/a\n"
            "seconds_since_last_applied: soon\nEND"
        )

        assert result.crc_errors == 0
        assert result.seconds_since_last_applied is None


class TestDebugInfoParsing:
    """Tests for debug info parsing."""

    def test_parse_full_debug_info(self):
        lines = [
            "query_time: 1.5",
            "index_time: 0.8",
            "filter_time: 0.2",
            "terms: 3",
            "ngrams: 10",
            "candidates: 1000",
            "after_intersection: 500",
            "after_not: 450",
            "after_filters: 100",
            "final: 50",
            "optimization: fast_path",
            "limit: 100",
            "offset: 0",
        ]
        result = MygramClient._parse_debug_info(lines)

        assert isinstance(result, DebugInfo)
        assert result.query_time_ms == 1.5
        assert result.index_time_ms == 0.8
        assert result.filter_time_ms == 0.2
        assert result.terms == 3
        assert result.ngrams == 10
        assert result.candidates == 1000
        assert result.after_intersection == 500
        assert result.after_not == 450
        assert result.after_filters == 100
        assert result.final == 50
        assert result.optimization == "fast_path"
        assert result.limit == 100
        assert result.offset == 0

    def test_parse_debug_info_with_default_markers(self):
        lines = [
            "limit: 1000 (default)",
            "offset: 0 (default)",
        ]
        result = MygramClient._parse_debug_info(lines)

        assert result.limit == 1000
        assert result.offset == 0

    def test_parse_debug_info_with_cache_fields(self):
        lines = [
            "query_time: 1.5",
            "terms: 2",
            "sort: id DESC",
            "cache: hit",
            "cache_age_ms: 123.4",
            "cache_saved_ms: 2100.0",
        ]
        result = MygramClient._parse_debug_info(lines)

        assert result.query_time_ms == 1.5
        assert result.sort == "id DESC"
        assert result.cache == "hit"
        assert result.cache_age_ms == 123.4
        assert result.cache_saved_ms == 2100.0

    def test_parse_debug_info_with_cache_miss_fields(self):
        lines = [
            "cache: miss",
            "cache_reason: invalidated",
            "cache_cost_ms: 18.250",
            "cache_key: articles|python",
            "highlight: on",
        ]
        result = MygramClient._parse_debug_info(lines)

        assert result.cache == "miss"
        assert result.cache_reason == "invalidated"
        assert result.cache_cost_ms == 18.25
        assert result.cache_key == "articles|python"
        assert result.highlight is True


class TestDumpStatusParsing:
    """Tests for dump status response parsing."""

    def test_parse_dump_status_idle(self):
        response = """OK DUMP_STATUS
status: idle"""
        result = MygramClient._parse_dump_status_response(response)

        assert isinstance(result, DumpStatus)
        assert result.status == "idle"
        assert result.filepath == ""
        assert result.tables_total == 0

    def test_parse_dump_status_saving(self):
        response = """OK DUMP_STATUS
status: saving
filepath: /backup/dump.dmp
tables_total: 5
tables_processed: 2
current_table: articles
elapsed_seconds: 3.5"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.status == "saving"
        assert result.filepath == "/backup/dump.dmp"
        assert result.tables_total == 5
        assert result.tables_processed == 2
        assert result.current_table == "articles"
        assert result.elapsed_seconds == 3.5

    def test_parse_dump_status_with_error(self):
        response = """OK DUMP_STATUS
status: failed
error: disk full"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.status == "failed"
        assert result.error == "disk full"

    def test_parse_dump_status_with_progress_flags(self):
        response = """OK DUMP_STATUS
save_in_progress: true
load_in_progress: false
status: saving
result_filepath: /backup/output.dmp"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.save_in_progress is True
        assert result.load_in_progress is False
        assert result.result_filepath == "/backup/output.dmp"

    def test_parse_invalid_dump_status_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid DUMP STATUS"):
            MygramClient._parse_dump_status_response("INVALID")


class TestCacheStatsParsing:
    """Tests for cache stats response parsing."""

    def test_parse_cache_stats_go_format(self):
        """Parse cache stats with Go-client key format."""
        response = """OK CACHE_STATS
cache_enabled: 1
cache_hits: 5000
cache_misses: 1000
cache_hit_rate: 83.3
cache_current_entries: 500
cache_memory_bytes: 10485760
cache_evictions: 50"""
        result = MygramClient._parse_cache_stats_response(response)

        assert isinstance(result, CacheStats)
        assert result.enabled is True
        assert result.hits == 5000
        assert result.misses == 1000
        assert result.hit_rate == 83.3
        assert result.current_entries == 500
        assert result.memory_bytes == 10485760
        assert result.evictions == 50

    def test_parse_cache_stats_node_format(self):
        """Parse cache stats with Node.js-client key format."""
        response = """OK CACHE_STATS
enabled: true
max_memory_mb: 32.0
current_memory_mb: 10.5
entries: 500
hits: 5000
misses: 1000
hit_rate: 83.3%
evictions: 50
ttl_seconds: 3600"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.enabled is True
        assert result.max_memory_mb == 32.0
        assert result.current_memory_mb == 10.5
        assert result.current_entries == 500
        assert result.hits == 5000
        assert result.misses == 1000
        assert result.hit_rate == 83.3
        assert result.evictions == 50
        assert result.ttl_seconds == 3600

    def test_parse_cache_stats_disabled(self):
        response = """OK CACHE_STATS
cache_enabled: 0
cache_hits: 0
cache_misses: 0"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.enabled is False
        assert result.hits == 0

    def test_parse_cache_stats_full_response(self):
        """Every counter the server reports is surfaced on CacheStats."""
        response = """OK CACHE_STATS

# Cache
enabled: true
total_queries: 6000
cache_hits: 5000
cache_misses: 1000
hit_rate: 0.8333
current_entries: 500
current_memory_bytes: 10485760
invalidation_index_memory_bytes: 4096
invalidation_queue_memory_bytes: 2048
accounted_memory_bytes: 10491904
evictions: 50
ttl_expirations: 7
rejection_count: 9
rejection_oversize: 4
rejection_memory_budget: 3
rejection_duplicate: 2
stale_entry_removals: 6
decompression_failures: 1
stale_lru_entries: 8
invalidations_immediate: 30
invalidations_deferred: 20
invalidations_batches: 5
avg_cache_hit_time_ms: 0.250
avg_cache_miss_time_ms: 12.500
total_time_saved_ms: 61250.000

END"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.total_queries == 6000
        assert result.hit_rate == 0.8333
        assert result.invalidation_index_memory_bytes == 4096
        assert result.invalidation_queue_memory_bytes == 2048
        assert result.accounted_memory_bytes == 10491904
        assert result.ttl_expirations == 7
        assert result.rejection_count == 9
        assert result.rejection_oversize == 4
        assert result.rejection_memory_budget == 3
        assert result.rejection_duplicate == 2
        assert result.stale_entry_removals == 6
        assert result.decompression_failures == 1
        assert result.stale_lru_entries == 8
        assert result.invalidations_immediate == 30
        assert result.invalidations_deferred == 20
        assert result.invalidations_batches == 5
        assert result.avg_cache_hit_time_ms == 0.25
        assert result.avg_cache_miss_time_ms == 12.5
        assert result.total_time_saved_ms == 61250.0

    def test_parse_cache_stats_older_server_keeps_defaults(self):
        response = """OK CACHE_STATS
enabled: true
cache_hits: 1
cache_misses: 0"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.total_queries == 0
        assert result.avg_cache_hit_time_ms is None
        assert result.total_time_saved_ms == 0.0

    def test_parse_invalid_cache_stats_raises_error(self):
        with pytest.raises(ProtocolError, match="Invalid CACHE STATS"):
            MygramClient._parse_cache_stats_response("INVALID")


class TestDumpSaveResponseParsing:
    """Tests for dump_save response validation."""

    def test_parse_dump_started_response(self):
        response = "OK DUMP_STARTED /backup/dump.dmp"
        assert response.startswith("OK DUMP_STARTED ")
        filepath = response[16:]
        assert filepath == "/backup/dump.dmp"

    def test_parse_dump_saved_response(self):
        response = "OK DUMP_SAVED /backup/dump.dmp"
        assert response.startswith("OK DUMP_SAVED ")
        filepath = response[14:]
        assert filepath == "/backup/dump.dmp"

    def test_invalid_dump_save_response(self):
        """Neither DUMP_STARTED nor DUMP_SAVED should raise ProtocolError."""
        response = "OK SOMETHING_ELSE"
        assert not response.startswith("OK DUMP_STARTED ")
        assert not response.startswith("OK DUMP_SAVED ")


class TestDumpStatusParsingEdgeCases:
    """Edge case tests for dump status parsing."""

    def test_parse_dump_status_completed(self):
        response = """OK DUMP_STATUS
status: completed
filepath: /backup/dump.dmp
tables_total: 5
tables_processed: 5
elapsed_seconds: 12.3
result_filepath: /backup/dump.dmp"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.status == "completed"
        assert result.tables_total == 5
        assert result.tables_processed == 5
        assert result.elapsed_seconds == 12.3
        assert result.result_filepath == "/backup/dump.dmp"

    def test_parse_dump_status_loading(self):
        response = """OK DUMP_STATUS
status: loading
load_in_progress: true
filepath: /backup/dump.dmp"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.status == "loading"
        assert result.load_in_progress is True

    def test_parse_dump_status_header_only(self):
        response = "OK DUMP_STATUS"
        result = MygramClient._parse_dump_status_response(response)

        assert result.status == ""
        assert result.filepath == ""

    def test_parse_dump_status_with_end_marker(self):
        response = """OK DUMP_STATUS
status: idle
END"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.status == "idle"

    def test_parse_dump_status_real_server_format(self):
        """Parse actual server response format."""
        response = """OK DUMP_STATUS
save_in_progress: false
load_in_progress: false
replication_paused_for_dump: false
status: IDLE
END"""
        result = MygramClient._parse_dump_status_response(response)

        assert result.save_in_progress is False
        assert result.load_in_progress is False
        assert result.status == "IDLE"


class TestCacheStatsParsingEdgeCases:
    """Edge case tests for cache stats parsing."""

    def test_parse_cache_stats_header_only(self):
        response = "OK CACHE_STATS"
        result = MygramClient._parse_cache_stats_response(response)

        assert result.enabled is False
        assert result.hits == 0

    def test_parse_cache_stats_real_server_format(self):
        """Parse actual server response format with section header and END."""
        response = """OK CACHE_STATS

# Cache
enabled: true
total_queries: 16
cache_hits: 0
cache_misses: 16
hit_rate: 0.0000
current_entries: 0
current_memory_bytes: 0
evictions: 0
ttl_expirations: 0
invalidations_immediate: 0
invalidations_deferred: 0
invalidations_batches: 0
avg_cache_miss_time_ms: 0.000
total_time_saved_ms: 0.000

END"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.enabled is True
        assert result.hits == 0
        assert result.misses == 16
        assert result.hit_rate == 0.0
        assert result.current_entries == 0
        assert result.memory_bytes == 0
        assert result.evictions == 0

    def test_parse_cache_stats_current_memory_bytes_maps_to_memory_bytes(self):
        """current_memory_bytes key should map to memory_bytes field."""
        response = """OK CACHE_STATS
current_memory_bytes: 10485760
current_entries: 42
END"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.memory_bytes == 10485760
        assert result.current_entries == 42

    def test_parse_cache_stats_section_header_skipped(self):
        """Lines starting with # should be ignored."""
        response = """OK CACHE_STATS
# Cache
# Metrics
cache_hits: 100
END"""
        result = MygramClient._parse_cache_stats_response(response)

        assert result.hits == 100

    def test_parse_cache_stats_hit_rate_without_percent(self):
        response = """OK CACHE_STATS
hit_rate: 83.3"""
        result = MygramClient._parse_cache_stats_response(response)
        assert result.hit_rate == 83.3

    def test_parse_cache_stats_enabled_true_string(self):
        response = """OK CACHE_STATS
enabled: true"""
        result = MygramClient._parse_cache_stats_response(response)
        assert result.enabled is True

    def test_parse_cache_stats_enabled_one_string(self):
        response = """OK CACHE_STATS
cache_enabled: 1"""
        result = MygramClient._parse_cache_stats_response(response)
        assert result.enabled is True

    def test_parse_cache_stats_disabled_false_string(self):
        response = """OK CACHE_STATS
enabled: false"""
        result = MygramClient._parse_cache_stats_response(response)
        assert result.enabled is False

    def test_parse_cache_stats_disabled_zero_string(self):
        response = """OK CACHE_STATS
cache_enabled: 0"""
        result = MygramClient._parse_cache_stats_response(response)
        assert result.enabled is False


class TestDebugInfoNewFieldsDefaults:
    """Tests for DebugInfo new field defaults."""

    def test_new_fields_default_to_none(self):
        debug = DebugInfo()
        assert debug.sort is None
        assert debug.cache is None
        assert debug.cache_age_ms is None
        assert debug.cache_saved_ms is None

    def test_parse_debug_info_cache_miss(self):
        lines = [
            "cache: miss",
        ]
        result = MygramClient._parse_debug_info(lines)
        assert result.cache == "miss"
        assert result.cache_age_ms is None
        assert result.cache_saved_ms is None

    def test_parse_debug_info_cache_disabled(self):
        lines = [
            "cache: disabled",
        ]
        result = MygramClient._parse_debug_info(lines)
        assert result.cache == "disabled"


class TestAsyncContextManager:
    """Tests for async context manager support."""

    def test_client_has_aenter_and_aexit(self):
        client = MygramClient()
        assert hasattr(client, "__aenter__")
        assert hasattr(client, "__aexit__")
        assert asyncio.iscoroutinefunction(client.__aenter__)
        assert asyncio.iscoroutinefunction(client.__aexit__)

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_disconnects(self):
        """Context manager should call connect on enter and disconnect on exit."""
        connect_called = False
        disconnect_called = False

        client = MygramClient()

        async def mock_connect():
            nonlocal connect_called
            connect_called = True
            client._connected = True

        async def mock_disconnect():
            nonlocal disconnect_called
            disconnect_called = True
            client._connected = False

        client.connect = mock_connect
        client.disconnect = mock_disconnect

        async with client:
            assert connect_called
            assert not disconnect_called

        assert disconnect_called

    @pytest.mark.asyncio
    async def test_context_manager_disconnects_on_exception(self):
        """Context manager should disconnect even when exception occurs."""
        disconnect_called = False

        client = MygramClient()

        async def mock_connect():
            client._connected = True

        async def mock_disconnect():
            nonlocal disconnect_called
            disconnect_called = True
            client._connected = False

        client.connect = mock_connect
        client.disconnect = mock_disconnect

        with pytest.raises(RuntimeError, match="test error"):
            async with client:
                raise RuntimeError("test error")

        assert disconnect_called
