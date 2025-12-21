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
    MygramClient,
    SearchOptions,
    simplify_search_expression,
)

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
