"""Tests for MygramClient."""
import pytest

from mygramdb_client import (
    ClientConfig,
    CountResponse,
    DebugInfo,
    Document,
    MygramClient,
    ReplicationStatus,
    SearchResponse,
    ServerInfo,
)
from mygramdb_client.errors import ProtocolError


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
