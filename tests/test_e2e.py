"""
End-to-end tests for MygramDB client against a real server.

These tests require a running MygramDB server on localhost:11016.
Tests are skipped if the server is not available.
"""
import asyncio
import os

import pytest

from mygramdb_client import (
    ClientConfig,
    CountOptions,
    FacetOptions,
    HighlightOptions,
    MygramClient,
    SearchOptions,
    simplify_search_expression,
)
from mygramdb_client.errors import ProtocolError

TEST_HOST = os.environ.get("MYGRAM_HOST", "127.0.0.1")
TEST_PORT = int(os.environ.get("MYGRAM_PORT", "11016"))


async def is_server_available() -> bool:
    """Check if the MygramDB server is available."""
    client = MygramClient(ClientConfig(host=TEST_HOST, port=TEST_PORT, timeout=1.0))
    try:
        await client.connect()
        await client.disconnect()
        return True
    except Exception:
        return False


@pytest.fixture
async def client():
    """Create a connected client for tests."""
    client = MygramClient(ClientConfig(host=TEST_HOST, port=TEST_PORT, timeout=5.0))
    await client.connect()
    yield client
    await client.disconnect()


# Check server availability once at module load
_server_available = None


def get_server_available():
    global _server_available
    if _server_available is None:
        _server_available = asyncio.run(is_server_available())
    return _server_available


# Skip all tests if server is not available
pytestmark = pytest.mark.skipif(
    not get_server_available(),
    reason="MygramDB server is not available"
)


class TestConnection:
    """Connection tests."""

    async def test_connect_successfully(self, client):
        assert client.is_connected() is True

    async def test_disconnect_successfully(self):
        client = MygramClient(ClientConfig(host=TEST_HOST, port=TEST_PORT))
        await client.connect()
        assert client.is_connected() is True

        await client.disconnect()
        assert client.is_connected() is False


class TestInfo:
    """Server info tests."""

    async def test_return_server_info(self, client):
        info = await client.info()

        assert info is not None
        assert "MygramDB" in info.version or info.version != ""
        assert isinstance(info.uptime_seconds, int)
        assert info.uptime_seconds >= 0
        assert isinstance(info.total_requests, int)
        assert isinstance(info.active_connections, int)
        assert info.active_connections >= 1
        assert isinstance(info.index_size_bytes, int)
        assert isinstance(info.doc_count, int)
        assert isinstance(info.tables, list)


class TestConfig:
    """Server config tests."""

    async def test_return_server_config_in_yaml(self, client):
        config = await client.get_config()

        assert config is not None
        assert isinstance(config, str)
        assert len(config) > 0
        assert "api:" in config or "port:" in config


class TestReplicationStatus:
    """Replication status tests."""

    async def test_return_replication_status(self, client):
        status = await client.get_replication_status()

        assert status is not None
        assert isinstance(status.running, bool)
        assert isinstance(status.gtid, str)
        assert isinstance(status.status_str, str)


class TestDebugMode:
    """Debug mode tests."""

    async def test_enable_and_disable_debug_mode(self, client):
        await client.enable_debug()
        await client.disable_debug()
        # No exception means success


class TestSearch:
    """Search tests."""

    async def test_execute_search_command(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "test")

        assert result is not None
        assert isinstance(result.total_count, int)
        assert result.total_count >= 0
        assert isinstance(result.results, list)

    async def test_execute_search_with_limit_option(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "test", SearchOptions(limit=5))

        assert result is not None
        assert len(result.results) <= 5

    async def test_execute_search_with_offset_option(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "test", SearchOptions(limit=10, offset=5))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_execute_search_with_and_terms(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "hello", SearchOptions(and_terms=["world"]))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_execute_search_with_not_terms(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "hello", SearchOptions(not_terms=["goodbye"]))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_return_debug_info_when_enabled(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")
        if info.doc_count == 0:
            pytest.skip("No documents indexed (debug info requires search results)")

        await client.enable_debug()
        table = info.tables[0]
        result = await client.search(table, "test")
        await client.disable_debug()

        assert result.debug is not None
        assert isinstance(result.debug.query_time_ms, float)


class TestCount:
    """Count tests."""

    async def test_execute_count_command(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.count(table, "test")

        assert result is not None
        assert isinstance(result.count, int)
        assert result.count >= 0

    async def test_execute_count_with_and_terms(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.count(table, "hello", CountOptions(and_terms=["world"]))

        assert result is not None
        assert isinstance(result.count, int)

    async def test_execute_count_with_not_terms(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.count(table, "hello", CountOptions(not_terms=["goodbye"]))

        assert result is not None
        assert isinstance(result.count, int)

    async def test_return_debug_info_when_enabled(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")
        if info.doc_count == 0:
            pytest.skip("No documents indexed (debug info requires search results)")

        await client.enable_debug()
        table = info.tables[0]
        result = await client.count(table, "test")
        await client.disable_debug()

        assert result.debug is not None
        assert isinstance(result.debug.query_time_ms, float)


class TestSearchWithWebStyleExpressions:
    """Search with web-style expressions tests."""

    async def test_search_with_simple_terms_and(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        expr = simplify_search_expression("hello world")

        assert expr.main_term == "hello"
        assert expr.and_terms == ["world"]

        result = await client.search(table, expr.main_term, SearchOptions(
            and_terms=expr.and_terms,
            not_terms=expr.not_terms
        ))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_search_with_required_terms_plus(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        expr = simplify_search_expression("+golang +tutorial")
        result = await client.search(table, expr.main_term, SearchOptions(
            and_terms=expr.and_terms,
            not_terms=expr.not_terms
        ))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_search_with_excluded_terms_minus(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        expr = simplify_search_expression("+programming -java")
        result = await client.search(table, expr.main_term, SearchOptions(
            and_terms=expr.and_terms,
            not_terms=expr.not_terms
        ))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_search_with_quoted_phrase(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        expr = simplify_search_expression('"machine learning" tutorial')
        result = await client.search(table, expr.main_term, SearchOptions(
            and_terms=expr.and_terms,
            not_terms=expr.not_terms
        ))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_search_with_japanese_terms_and_fullwidth_space(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        expr = simplify_search_expression("機械学習\u3000チュートリアル")

        assert expr.main_term == "機械学習"
        assert expr.and_terms == ["チュートリアル"]

        result = await client.search(table, expr.main_term, SearchOptions(
            and_terms=expr.and_terms,
            not_terms=expr.not_terms
        ))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_count_with_web_style_expression(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        expr = simplify_search_expression("+hello +world -goodbye")
        result = await client.count(table, expr.main_term, CountOptions(
            and_terms=expr.and_terms,
            not_terms=expr.not_terms
        ))

        assert result is not None
        assert isinstance(result.count, int)


class TestCacheOperations:
    """Cache operation tests."""

    async def test_cache_stats(self, client):
        stats = await client.cache_stats()

        assert stats is not None
        assert isinstance(stats.enabled, bool)
        assert isinstance(stats.hits, int)
        assert isinstance(stats.misses, int)

    async def test_cache_clear_all(self, client):
        await client.cache_clear()
        # No exception means success

    async def test_cache_clear_specific_table(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        await client.cache_clear(info.tables[0])
        # No exception means success

    async def test_cache_enable_disable(self, client):
        await client.cache_enable()
        await client.cache_disable()
        await client.cache_enable()
        # No exception means success


class TestDumpOperations:
    """Dump operation tests."""

    async def test_dump_status(self, client):
        status = await client.dump_status()

        assert status is not None
        assert isinstance(status.status, str)
        assert isinstance(status.tables_total, int)
        assert isinstance(status.tables_processed, int)


class TestOptimize:
    """Optimize tests."""

    async def test_optimize_specific_table(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        await client.optimize(info.tables[0])
        # No exception means success


class TestV16Features:
    """
    End-to-end tests for MygramDB v1.6 features.

    Some features require specific server configuration (e.g. HIGHLIGHT/
    _score require ``memory.verify_text: ascii|all``). Tests wrap optional
    features in try/except ``ProtocolError`` so they pass even if the
    server is running with defaults.
    """

    async def test_fuzzy_distance_one(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "hello", SearchOptions(fuzzy=1))

        assert result is not None
        assert isinstance(result.total_count, int)
        assert result.total_count >= 0

    async def test_fuzzy_distance_two(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search(table, "hello", SearchOptions(fuzzy=2))

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_highlight_default(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        try:
            result = await client.search(
                table, "hello",
                SearchOptions(highlight=HighlightOptions()),
            )
        except ProtocolError as e:
            pytest.skip(f"HIGHLIGHT not supported: {e}")

        assert result is not None
        assert isinstance(result.total_count, int)
        for r in result.results:
            assert r.snippet is not None

    async def test_highlight_custom_tags(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        try:
            result = await client.search(
                table, "hello",
                SearchOptions(highlight=HighlightOptions(
                    open_tag="<mark>",
                    close_tag="</mark>",
                    snippet_len=150,
                    max_fragments=2,
                )),
            )
        except ProtocolError as e:
            pytest.skip(f"HIGHLIGHT not supported: {e}")

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_score_sort(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        try:
            result = await client.search(
                table, "hello",
                SearchOptions(sort_column="_score", sort_desc=True),
            )
        except ProtocolError as e:
            pytest.skip(f"_score sort not supported: {e}")

        assert result is not None
        assert isinstance(result.total_count, int)

    async def test_facet_no_query(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        try:
            # We don't know which columns are facetable, try a common one
            result = await client.facet(table, "status")
        except ProtocolError as e:
            pytest.skip(f"FACET not supported or column not faceted: {e}")

        assert result is not None
        assert isinstance(result.results, list)

    async def test_facet_with_query(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        try:
            result = await client.facet(
                table, "status",
                FacetOptions(query="test", limit=10),
            )
        except ProtocolError as e:
            pytest.skip(f"FACET not supported or column not faceted: {e}")

        assert result is not None
        assert isinstance(result.results, list)


class TestAsyncContextManagerE2E:
    """Async context manager E2E tests."""

    async def test_context_manager_connect_and_disconnect(self):
        async with MygramClient(ClientConfig(
            host=TEST_HOST, port=TEST_PORT, timeout=5.0
        )) as client:
            assert client.is_connected() is True
            info = await client.info()
            assert info is not None

    async def test_context_manager_disconnects_after_exit(self):
        client = MygramClient(ClientConfig(
            host=TEST_HOST, port=TEST_PORT, timeout=5.0
        ))
        async with client:
            assert client.is_connected() is True

        assert client.is_connected() is False
