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
    MygramPool,
    PoolConfig,
    RetryPolicy,
    SearchOptions,
    SearchRawOptions,
    convert_search_expression,
    simplify_search_expression,
)
from mygramdb_client.errors import ProtocolError, ServerError

# Server-side gating errors (e.g. HIGHLIGHT requires verify_text, FACET requires
# a faceted column) surface as ServerError; legacy server builds emit raw
# protocol errors. Either is a valid round-trip of the new clause.
_OPTIONAL_FEATURE_ERRORS = (ProtocolError, ServerError)

TEST_HOST = os.environ.get("MYGRAM_HOST", "127.0.0.1")
TEST_PORT = int(os.environ.get("MYGRAM_PORT", "11016"))
TEST_ADMIN_TOKEN = os.environ.get("MYGRAM_ADMIN_TOKEN", "")

# Set to "1" by tests/docker/run-e2e.sh, which boots a server seeded with the
# fixed dataset in tests/docker/mysql-init. Only then can we assert exact result
# sets; against an arbitrary developer server these are skipped.
SEEDED = os.environ.get("MYGRAM_E2E_SEEDED") == "1"


def e2e_config(**overrides) -> ClientConfig:
    """
    Build a client config pointed at the e2e server.

    ``MYGRAM_ADMIN_TOKEN`` is forwarded as ``admin_token`` so the client
    authenticates on connect: from MygramDB v1.10 a server whose TCP listener
    is not loopback-only requires ``AUTH`` before any administrative command.
    An empty value (a server started without a token) sends no AUTH at all.
    """
    return ClientConfig(
        host=TEST_HOST,
        port=TEST_PORT,
        admin_token=TEST_ADMIN_TOKEN,
        **overrides,
    )


async def is_server_available() -> bool:
    """Check if the MygramDB server is available."""
    client = MygramClient(e2e_config(timeout=1.0))
    try:
        await client.connect()
        await client.disconnect()
        return True
    except Exception:
        return False


@pytest.fixture
async def client():
    """Create a connected client for tests."""
    client = MygramClient(e2e_config(timeout=5.0))
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
        client = MygramClient(e2e_config())
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


class TestSearchOptions:
    """
    Round-trip tests for the typed search options: FUZZY, HIGHLIGHT and
    relevance ordering.

    Some of these require specific server configuration (HIGHLIGHT and
    ``_score`` need ``memory.verify_text: ascii|all``), so they wrap the call
    in try/except ``_OPTIONAL_FEATURE_ERRORS`` (ProtocolError or ServerError)
    and skip rather than fail against a server running with defaults.
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
        except _OPTIONAL_FEATURE_ERRORS as e:
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
        except _OPTIONAL_FEATURE_ERRORS as e:
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
        except _OPTIONAL_FEATURE_ERRORS as e:
            pytest.skip(f"_score sort not supported: {e}")

        assert result is not None
        assert isinstance(result.total_count, int)


class TestFacet:
    """FACET aggregation against whichever columns the server has configured."""

    async def test_facet_no_query(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        try:
            # We don't know which columns are facetable, try a common one
            result = await client.facet(table, "status")
        except _OPTIONAL_FEATURE_ERRORS as e:
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
        except _OPTIONAL_FEATURE_ERRORS as e:
            pytest.skip(f"FACET not supported or column not faceted: {e}")

        assert result is not None
        assert isinstance(result.results, list)


class TestAsyncContextManagerE2E:
    """Async context manager E2E tests."""

    async def test_context_manager_connect_and_disconnect(self):
        async with MygramClient(e2e_config(timeout=5.0)) as client:
            assert client.is_connected() is True
            info = await client.info()
            assert info is not None

    async def test_context_manager_disconnects_after_exit(self):
        client = MygramClient(e2e_config(timeout=5.0))
        async with client:
            assert client.is_connected() is True

        assert client.is_connected() is False


class TestTableIdentity:
    """A database-qualified identity addresses the same table as a bare name."""

    async def test_database_qualified_identity_matches_bare(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        # info.tables may already be qualified (database.table) or bare.
        reported = info.tables[0]
        bare = reported.split(".", 1)[1] if "." in reported else reported

        via_reported = await client.search(reported, "test", SearchOptions(limit=5))
        via_bare = await client.search(bare, "test", SearchOptions(limit=5))

        assert via_reported.total_count == via_bare.total_count


class TestSearchRaw:
    """
    Unquoted boolean transport against a live server.

    Against an arbitrary dataset only framing and parsing can be asserted, so
    these check that each expression shape round-trips cleanly.
    """

    async def test_search_raw_boolean_or(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search_raw(
            table, "hello OR world", SearchRawOptions(limit=5)
        )

        assert result is not None
        assert isinstance(result.total_count, int)
        assert isinstance(result.results, list)

    async def test_search_raw_grouped_expression(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        raw = convert_search_expression("hello OR (world AND test)")
        result = await client.search_raw(table, raw, SearchRawOptions(limit=5))

        assert isinstance(result.total_count, int)

    async def test_search_raw_or_group_nested_under_and(self, client):
        info = await client.info()
        if not info.tables:
            pytest.skip("No tables available")

        table = info.tables[0]
        result = await client.search_raw(
            table, "(hello OR world) AND test", SearchRawOptions(limit=5)
        )
        assert isinstance(result.total_count, int)
        assert isinstance(result.results, list)


class TestRuntimeVariables:
    """SET / SHOW VARIABLES round-trip, tolerating an immutable-variable build."""

    async def test_runtime_variables_round_trip(self, client):
        # Some builds mark all variables immutable; tolerate a server rejection
        # as long as the protocol round-trips cleanly.
        try:
            await client.set_variable("logging.level", "info")
        except _OPTIONAL_FEATURE_ERRORS:
            pass
        variables = await client.show_variables("logging%")
        assert isinstance(variables, str)
        assert len(variables) > 0


class TestSync:
    """On-demand sync commands frame and parse against a live server."""

    async def test_sync_status_round_trip(self, client):
        status = await client.sync_status()
        assert isinstance(status, str)
        assert "SYNC_STATUS" in status

    async def test_sync_stop_with_no_active_sync(self, client):
        # With nothing running the server may answer OK or ERROR; both prove the
        # command framed correctly.
        try:
            result = await client.sync_stop()
            assert isinstance(result, str)
        except _OPTIONAL_FEATURE_ERRORS:
            pass


class TestPool:
    """The connection pool driven against a live server."""

    async def test_pool_delegation_round_trip(self):
        pool = MygramPool(
            e2e_config(),
            PoolConfig(min_connections=1, max_connections=3),
        )
        await pool.open()
        try:
            info = await pool.info()
            assert info.version != "" or isinstance(info.uptime_seconds, int)
            if info.tables:
                result = await pool.search(
                    info.tables[0], "test", SearchOptions(limit=5)
                )
                assert isinstance(result.total_count, int)
            stats = pool.stats()
            assert stats.total_acquires >= 1
            assert stats.total_connections >= 1
        finally:
            await pool.close()

    async def test_pool_concurrent_requests(self):
        pool = MygramPool(
            e2e_config(),
            PoolConfig(
                min_connections=2,
                max_connections=4,
                retry_policy=RetryPolicy(max_attempts=2),
            ),
        )
        await pool.open()
        try:
            info = await pool.info()
            if not info.tables:
                pytest.skip("No tables available")
            table = info.tables[0]
            results = await asyncio.gather(
                *[pool.search(table, "test", SearchOptions(limit=3))
                  for _ in range(12)]
            )
            assert len(results) == 12
            assert all(isinstance(r.total_count, int) for r in results)
            # Concurrency never exceeded the pool ceiling.
            assert pool.stats().total_connections <= 4
        finally:
            await pool.close()


@pytest.mark.skipif(not SEEDED, reason="requires MYGRAM_E2E_SEEDED=1 (docker e2e)")
class TestSeededDataset:
    """
    Deterministic assertions against the fixed dataset seeded by
    tests/docker/run-e2e.sh. See tests/docker/mysql-init/02-seed.sql.
    """

    TABLE = "testdb.articles"  # database-qualified identity (v1.7)

    @staticmethod
    def _ids(response) -> list:
        return sorted(r.primary_key for r in response.results)

    async def test_search_resolves_qualified_identity(self, client):
        res = await client.search(self.TABLE, "python")
        assert res.total_count == 1
        assert self._ids(res) == ["3"]

    async def test_multi_word_phrase_excludes_disabled_rows(self, client):
        # id 6 also contains "machine learning" but is enabled=0 (hidden).
        res = await client.search(self.TABLE, "machine learning")
        assert res.total_count == 1
        assert self._ids(res) == ["3"]

    async def test_matches_japanese_content(self, client):
        res = await client.search(self.TABLE, "機械学習")
        assert res.total_count == 2
        assert self._ids(res) == ["1", "5"]

    async def test_count_matches_single_row(self, client):
        res = await client.count(self.TABLE, "golang")
        assert res.count == 1

    async def test_search_raw_boolean_or(self, client):
        res = await client.search_raw(self.TABLE, "ruby OR python")
        assert res.total_count == 2
        assert self._ids(res) == ["2", "3"]

    async def test_search_raw_or_group_nested_under_and(self, client):
        # (ruby OR python) AND machine -> only id 3 ("python machine learning")
        # carries both an OR-branch term and "machine". This is the exact shape
        # that failed to parse before unquoted transport (MygramDB v1.8).
        res = await client.search_raw(self.TABLE, "(ruby OR python) AND machine")
        assert res.total_count == 1
        assert self._ids(res) == ["3"]

    async def test_bare_and_qualified_resolve_identically(self, client):
        qualified = await client.search("testdb.articles", "python")
        bare = await client.search("articles", "python")
        assert bare.total_count == qualified.total_count
        assert bare.total_count == 1

    async def test_facet_aggregates_enabled_rows_by_category(self, client):
        resp = await client.facet(self.TABLE, "category")
        by_value = {v.value: v.count for v in resp.results}
        assert by_value.get("tech") == 3
        assert by_value.get("science") == 2

    async def test_get_returns_seeded_document(self, client):
        doc = await client.get(self.TABLE, "1")
        assert doc.primary_key == "1"
        assert doc.fields.get("category") == "tech"

    async def test_search_with_highlights_wraps_match(self, client):
        res = await client.search_with_highlights(
            self.TABLE, "python",
            SearchOptions(highlight=HighlightOptions(open_tag="<em>", close_tag="</em>")),
        )
        assert res.total_count == 1
        assert res.results[0].snippet is not None
        assert "<em>python</em>" in res.results[0].snippet

    async def test_pool_search_matches_direct_client(self):
        pool = MygramPool(
            e2e_config(),
            PoolConfig(min_connections=2, max_connections=4),
        )
        await pool.open()
        try:
            res = await pool.search(self.TABLE, "python")
            assert res.total_count == 1
            assert self._ids(res) == ["3"]

            # Concurrent identical queries all resolve to the same seeded row.
            batch = await asyncio.gather(
                *[pool.search(self.TABLE, "python") for _ in range(8)]
            )
            assert all(self._ids(r) == ["3"] for r in batch)
        finally:
            await pool.close()
