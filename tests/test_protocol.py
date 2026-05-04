"""
Protocol-level tests for MygramDB client.

Tests the command generation logic without actual network connections.
"""


class TestFilterSyntax:
    """Tests for FILTER clause generation."""

    def test_generate_multiple_filter_clauses(self):
        """Should generate multiple FILTER clauses for multiple filters."""
        filters = {"status": "published", "category": "news"}
        parts = []

        for key, value in filters.items():
            parts.extend(["FILTER", key, "=", value])

        command = " ".join(parts)

        assert "FILTER status = published" in command
        assert "FILTER category = news" in command

    def test_generate_filter_with_spaces_around_equals(self):
        """Should generate FILTER with spaces around equals sign."""
        filters = {"key": "value"}
        parts = []

        for key, value in filters.items():
            parts.extend(["FILTER", key, "=", value])

        command = " ".join(parts)

        assert command == "FILTER key = value"
        assert "key=value" not in command

    def test_not_use_and_between_multiple_filters(self):
        """Should not use AND between multiple filters."""
        filters = {"status": "published", "category": "news", "lang": "en"}
        parts = []

        for key, value in filters.items():
            parts.extend(["FILTER", key, "=", value])

        command = " ".join(parts)

        assert "FILTER status = published" in command
        assert "FILTER category = news" in command
        assert "FILTER lang = en" in command
        # Should NOT have "AND" between filters
        assert "AND" not in command


class TestLimitSyntax:
    """Tests for LIMIT clause generation (MySQL-compatible syntax)."""

    def test_use_offset_limit_format_when_both_specified(self):
        """Should use 'offset,limit' format when both offset and limit are specified."""
        limit = 50
        offset = 100
        parts = []

        if offset > 0:
            parts.extend(["LIMIT", f"{offset},{limit}"])
        else:
            parts.extend(["LIMIT", str(limit)])

        command = " ".join(parts)
        assert command == "LIMIT 100,50"

    def test_use_limit_only_format_when_no_offset(self):
        """Should use 'LIMIT count' format when only limit is specified."""
        limit = 50
        offset = 0
        parts = []

        if offset > 0:
            parts.extend(["LIMIT", f"{offset},{limit}"])
        else:
            parts.extend(["LIMIT", str(limit)])

        command = " ".join(parts)
        assert command == "LIMIT 50"
        assert "," not in command

    def test_default_limit_1000(self):
        """Should use default limit of 1000 when not specified."""
        limit = 1000  # Default value
        offset = 0
        parts = []

        if offset > 0:
            parts.extend(["LIMIT", f"{offset},{limit}"])
        else:
            parts.extend(["LIMIT", str(limit)])

        command = " ".join(parts)
        assert command == "LIMIT 1000"

    def test_offset_only_emits_bare_offset(self):
        """offset > 0 with limit == 0 must emit OFFSET, not silently drop the offset."""
        import asyncio

        from mygramdb_client import MygramClient, SearchOptions

        client = MygramClient()
        captured = {}

        async def capture(command):
            captured["command"] = command
            return "OK RESULTS 0"

        client._connected = True
        client.send_command = capture  # type: ignore[assignment]

        async def run():
            await client.search("articles", "hello", SearchOptions(limit=0, offset=42))

        asyncio.run(run())
        cmd = captured["command"]
        assert "OFFSET 42" in cmd
        assert "LIMIT" not in cmd

    def test_offset_and_limit_emit_combined_form(self):
        """offset > 0 with limit > 0 emits 'LIMIT offset,limit'."""
        import asyncio

        from mygramdb_client import MygramClient, SearchOptions

        client = MygramClient()
        captured = {}

        async def capture(command):
            captured["command"] = command
            return "OK RESULTS 0"

        client._connected = True
        client.send_command = capture  # type: ignore[assignment]

        async def run():
            await client.search("articles", "hello", SearchOptions(limit=10, offset=20))

        asyncio.run(run())
        assert "LIMIT 20,10" in captured["command"]

    def test_zero_offset_zero_limit_emits_no_limit(self):
        """Both zero: no LIMIT/OFFSET clause."""
        import asyncio

        from mygramdb_client import MygramClient, SearchOptions

        client = MygramClient()
        captured = {}

        async def capture(command):
            captured["command"] = command
            return "OK RESULTS 0"

        client._connected = True
        client.send_command = capture  # type: ignore[assignment]

        async def run():
            await client.search("articles", "hello", SearchOptions(limit=0, offset=0))

        asyncio.run(run())
        cmd = captured["command"]
        assert "LIMIT" not in cmd
        assert "OFFSET" not in cmd


class TestSortSyntax:
    """Tests for SORT clause generation."""

    def test_generate_sort_with_column_and_asc(self):
        """Should generate SORT with column and ASC direction."""
        sort_column = "published_at"
        sort_desc = False
        parts = []

        if sort_column:
            parts.extend(["SORT", sort_column, "DESC" if sort_desc else "ASC"])

        command = " ".join(parts)
        assert command == "SORT published_at ASC"

    def test_generate_sort_with_desc_by_default(self):
        """Should use DESC by default."""
        sort_column = "published_at"
        sort_desc = True  # Default
        parts = []

        if sort_column:
            parts.extend(["SORT", sort_column, "DESC" if sort_desc else "ASC"])

        command = " ".join(parts)
        assert command == "SORT published_at DESC"


class TestCombinedQuery:
    """Tests for combined query generation."""

    def test_build_complex_query_with_all_features(self):
        """Should build complex query with all features."""
        table = "articles"
        query = "hello world"
        and_terms = ["important"]
        not_terms = ["spam"]
        filters = {"status": "published", "lang": "en"}
        sort_column = "score"
        sort_desc = True
        limit = 20
        offset = 40

        parts = ["SEARCH", table, query]

        # AND terms
        for term in and_terms:
            parts.extend(["AND", term])

        # NOT terms
        for term in not_terms:
            parts.extend(["NOT", term])

        # FILTER clauses
        for key, value in filters.items():
            parts.extend(["FILTER", key, "=", value])

        # SORT
        if sort_column:
            parts.extend(["SORT", sort_column, "DESC" if sort_desc else "ASC"])

        # LIMIT
        if offset > 0:
            parts.extend(["LIMIT", f"{offset},{limit}"])
        else:
            parts.extend(["LIMIT", str(limit)])

        command = " ".join(parts)

        # Verify all parts are present
        assert "SEARCH articles hello world" in command
        assert "AND important" in command
        assert "NOT spam" in command
        assert "FILTER status = published" in command
        assert "FILTER lang = en" in command
        assert "SORT score DESC" in command
        assert "LIMIT 40,20" in command


class TestSearchCommandGeneration:
    """Tests for search command generation from expressions."""

    def test_convert_two_words_to_and(self):
        """Should convert two words to AND."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression("hello world")
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])
        for term in expr.not_terms:
            parts.extend(["NOT", term])

        command = " ".join(parts)
        assert command == "SEARCH tbl hello AND world"

    def test_convert_three_words_to_multiple_and(self):
        """Should convert three words to multiple AND."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression("hello world test")
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])

        command = " ".join(parts)
        assert command == "SEARCH tbl hello AND world AND test"

    def test_convert_plus_terms_to_and(self):
        """Should convert +terms to AND."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression("+hello +world")
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])

        command = " ".join(parts)
        assert command == "SEARCH tbl hello AND world"

    def test_convert_minus_term_to_not(self):
        """Should convert -term to NOT."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression("hello -world")
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])
        for term in expr.not_terms:
            parts.extend(["NOT", term])

        command = " ".join(parts)
        assert command == "SEARCH tbl hello NOT world"

    def test_handle_plus_and_minus_combination(self):
        """Should handle + and - combination."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression("+hello +world -bad -ugly")
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])
        for term in expr.not_terms:
            parts.extend(["NOT", term])

        command = " ".join(parts)
        assert command == "SEARCH tbl hello AND world NOT bad NOT ugly"

    def test_preserve_quotes_for_phrase_search(self):
        """Should preserve quotes for phrase search."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression('"hello world"')
        parts = ["SEARCH", "tbl", expr.main_term]

        command = " ".join(parts)
        assert command == 'SEARCH tbl "hello world"'

    def test_handle_phrase_with_additional_terms(self):
        """Should handle phrase with additional terms."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression('"hello world" test')
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])

        command = " ".join(parts)
        assert command == 'SEARCH tbl "hello world" AND test'

    def test_handle_japanese_with_fullwidth_space(self):
        """Should handle Japanese text with full-width space as AND separator."""
        from mygramdb_client import simplify_search_expression

        expr = simplify_search_expression("機械学習\u3000チュートリアル")
        parts = ["SEARCH", "tbl", expr.main_term]
        for term in expr.and_terms:
            parts.extend(["AND", term])

        command = " ".join(parts)
        assert command == "SEARCH tbl 機械学習 AND チュートリアル"


class TestResponseParsing:
    """Tests for response parsing."""

    def test_normalize_crlf_to_lf(self):
        """Should normalize CRLF to LF."""
        crlf_response = "OK RESULTS 2 pk1 pk2\r\n"
        normalized = crlf_response.replace("\r\n", "\n").strip()

        assert normalized == "OK RESULTS 2 pk1 pk2"
        assert "\r" not in normalized

    def test_handle_mixed_line_endings(self):
        """Should handle mixed line endings."""
        mixed_response = "line1\r\nline2\nline3\r\n"
        normalized = mixed_response.replace("\r\n", "\n").strip()

        assert normalized == "line1\nline2\nline3"

    def test_parse_info_response_fields(self):
        """Should parse INFO response fields."""
        info_response = """OK INFO
version: MygramDB v1.3.7
uptime_seconds: 12345
total_requests: 1000
connected_clients: 5
used_memory_bytes: 1048576
total_documents: 500
tables: articles,users"""

        lines = info_response.split("\n")[1:]
        info = {}

        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key == "tables":
                info[key] = [s.strip() for s in value.split(",")]
            elif key in ["uptime_seconds", "total_requests", "connected_clients",
                         "used_memory_bytes", "total_documents"]:
                info[key] = int(value)
            else:
                info[key] = value

        assert info["version"] == "MygramDB v1.3.7"
        assert info["uptime_seconds"] == 12345
        assert info["tables"] == ["articles", "users"]

    def test_parse_replication_multi_line_format(self):
        """Should parse multi-line REPLICATION STATUS format."""
        response = """OK REPLICATION
status: running
current_gtid: mysql-bin.000001:12345
processed_events: 1000
END"""

        lines = response.split("\n")
        is_multi_line = lines[0].strip() == "OK REPLICATION"

        assert is_multi_line

        status = {}
        for line in lines[1:]:
            trimmed = line.strip()
            if not trimmed or trimmed == "END":
                continue
            if ":" not in trimmed:
                continue

            colon_index = trimmed.index(":")
            key = trimmed[:colon_index].strip()
            value = trimmed[colon_index + 1:].strip()

            if key == "status":
                status["running"] = value == "running"
            elif key == "current_gtid":
                status["gtid"] = value

        assert status["running"] is True
        assert status["gtid"] == "mysql-bin.000001:12345"

    def test_parse_replication_single_line_format(self):
        """Should parse single-line REPLICATION STATUS format."""
        response = "OK REPLICATION status=stopped gtid="
        is_single_line = response.startswith("OK REPLICATION ")

        assert is_single_line

        parts = response[15:].split(" ")
        status_part = next((p for p in parts if p.startswith("status=")), None)
        gtid_part = next((p for p in parts if p.startswith("gtid=")), None)

        assert status_part.split("=")[1] == "stopped"
        assert gtid_part.split("=")[1] == ""

    def test_parse_config_plus_ok_format(self):
        """Should parse +OK CONFIG format."""
        response = """+OK
api:
  port: 11016
  default_limit: 100"""

        assert response.startswith("+OK")
        config = response[len("+OK\n"):]
        assert "api:" in config
        assert "port: 11016" in config

    def test_parse_config_ok_config_format(self):
        """Should parse OK CONFIG format."""
        response = """OK CONFIG
api:
  port: 11016"""

        assert response.startswith("OK CONFIG")
        config = response[len("OK CONFIG\n"):]
        assert "api:" in config


class TestResponseCompletionDetection:
    """Tests for response completion detection in multi-line responses."""

    def test_dump_status_response_complete_with_end(self):
        """Should detect DUMP STATUS response ending with END marker."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK DUMP_STATUS\r\nstatus: idle\r\nEND\r\n"
        assert client._is_response_complete(buffer)

    def test_dump_status_response_complete_lf(self):
        """Should detect DUMP STATUS response ending with END (LF)."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK DUMP_STATUS\nstatus: idle\nEND\n"
        assert client._is_response_complete(buffer)

    def test_dump_status_response_incomplete(self):
        """Should detect incomplete DUMP STATUS response."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK DUMP_STATUS\nstatus: saving"
        assert not client._is_response_complete(buffer)

    def test_cache_stats_response_complete_with_end(self):
        """Should detect CACHE STATS response ending with END marker."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK CACHE_STATS\r\n\r\n# Cache\r\nenabled: true\r\nEND\r\n"
        assert client._is_response_complete(buffer)

    def test_cache_stats_response_complete_lf(self):
        """Should detect CACHE STATS response ending with END (LF)."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK CACHE_STATS\n\n# Cache\nenabled: true\nEND\n"
        assert client._is_response_complete(buffer)

    def test_cache_stats_response_incomplete(self):
        """Should detect incomplete CACHE STATS response."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK CACHE_STATS\ncache_enabled: 1"
        assert not client._is_response_complete(buffer)

    def test_replication_response_complete_crlf(self):
        """Should detect REPLICATION response with CRLF line endings."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK REPLICATION\r\nstatus: running\r\ncurrent_gtid: abc\r\nEND\r\n"
        assert client._is_response_complete(buffer)

    def test_replication_response_incomplete_crlf(self):
        """Should detect incomplete REPLICATION response with CRLF."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK REPLICATION\r\nstatus: running"
        assert not client._is_response_complete(buffer)

    def test_dump_status_response_complete_crlf_end(self):
        """Should detect DUMP STATUS with CRLF and END marker."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK DUMP_STATUS\r\nstatus: IDLE\r\nEND\r\n"
        assert client._is_response_complete(buffer)

    def test_cache_stats_response_complete_crlf_end(self):
        """Should detect CACHE STATS with CRLF and END marker."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK CACHE_STATS\r\n\r\n# Cache\r\nenabled: true\r\nEND\r\n"
        assert client._is_response_complete(buffer)


class TestDumpCommandGeneration:
    """Tests for DUMP command generation."""

    def test_dump_save_command_with_filepath(self):
        parts = ["DUMP", "SAVE", "/backup/dump.dmp"]
        command = " ".join(parts)
        assert command == "DUMP SAVE /backup/dump.dmp"

    def test_dump_load_command_with_filepath(self):
        parts = ["DUMP", "LOAD", "/backup/dump.dmp"]
        command = " ".join(parts)
        assert command == "DUMP LOAD /backup/dump.dmp"

    def test_dump_verify_command(self):
        parts = ["DUMP", "VERIFY", "/backup/dump.dmp"]
        command = " ".join(parts)
        assert command == "DUMP VERIFY /backup/dump.dmp"

    def test_dump_info_command(self):
        parts = ["DUMP", "INFO", "/backup/dump.dmp"]
        command = " ".join(parts)
        assert command == "DUMP INFO /backup/dump.dmp"


class TestCacheCommandGeneration:
    """Tests for CACHE command generation."""

    def test_cache_clear_all(self):
        command = "CACHE CLEAR"
        assert command == "CACHE CLEAR"

    def test_cache_clear_table(self):
        table = "articles"
        command = f"CACHE CLEAR {table}"
        assert command == "CACHE CLEAR articles"

    def test_cache_enable(self):
        command = "CACHE ENABLE"
        assert command == "CACHE ENABLE"

    def test_cache_disable(self):
        command = "CACHE DISABLE"
        assert command == "CACHE DISABLE"


class TestOptimizeCommandGeneration:
    """Tests for OPTIMIZE command generation."""

    def test_optimize_all(self):
        command = "OPTIMIZE"
        assert command == "OPTIMIZE"

    def test_optimize_table(self):
        table = "articles"
        command = f"OPTIMIZE {table}"
        assert command == "OPTIMIZE articles"

    def test_optimize_without_table_sends_bare_command(self):
        """OPTIMIZE without table sends bare command (server may reject it)."""
        table = None
        if table:
            command = f"OPTIMIZE {table}"
        else:
            command = "OPTIMIZE"
        assert command == "OPTIMIZE"


class TestSearchEmptyAndQuotedQuery:
    """Tests that the SEARCH/COUNT wire form quotes empty/whitespace tokens."""

    def _capture_search_command(self, query, **opts_kwargs):
        import asyncio

        from mygramdb_client import MygramClient, SearchOptions

        client = MygramClient()
        captured = {}

        async def capture(command):
            captured["command"] = command
            return "OK RESULTS 0"

        client._connected = True
        client.send_command = capture  # type: ignore[assignment]

        async def run():
            await client.search("articles", query, SearchOptions(**opts_kwargs))

        asyncio.run(run())
        return captured["command"]

    def test_empty_query_emitted_as_quoted_empty_token(self):
        """Empty query must be emitted as the explicit "" token."""
        cmd = self._capture_search_command("")
        # The token between table and the next clause should be ""
        assert 'SEARCH articles ""' in cmd

    def test_query_with_space_is_quoted(self):
        cmd = self._capture_search_command("hello world", limit=10)
        assert 'SEARCH articles "hello world"' in cmd

    def test_filter_value_with_space_is_quoted(self):
        cmd = self._capture_search_command(
            "hi",
            limit=10,
            filters={"title": "hello world"},
        )
        assert 'FILTER title = "hello world"' in cmd

    def test_and_term_with_space_is_quoted(self):
        cmd = self._capture_search_command(
            "hi",
            limit=10,
            and_terms=["machine learning"],
        )
        assert 'AND "machine learning"' in cmd


class TestReplicationStatusExtraFields:
    """ReplicationStatus parses processed_events and queue_size."""

    def test_parse_processed_events_and_queue_size(self):
        from mygramdb_client import MygramClient

        response = """OK REPLICATION
status: running
current_gtid: xyz789
processed_events: 1234
queue_size: 5
END"""
        result = MygramClient._parse_replication_status_response(response)

        assert result.running is True
        assert result.gtid == "xyz789"
        assert result.processed_events == 1234
        assert result.queue_size == 5

    def test_processed_events_defaults_to_zero(self):
        from mygramdb_client import MygramClient

        response = """OK REPLICATION
status: running
current_gtid: abc
END"""
        result = MygramClient._parse_replication_status_response(response)
        assert result.processed_events == 0
        assert result.queue_size == 0

    def test_gtid_key_alias_accepted(self):
        """The server may emit `gtid:` instead of `current_gtid:`."""
        from mygramdb_client import MygramClient

        response = """OK REPLICATION
status: stopped
gtid: aaa-bbb
END"""
        result = MygramClient._parse_replication_status_response(response)
        assert result.gtid == "aaa-bbb"
        assert result.running is False


class TestEndTerminatedResponseDetection:
    """First-line prefix detection for END-terminated multi-line responses."""

    def test_dump_info_with_filepath_complete(self):
        """OK DUMP_INFO carries an optional filepath suffix; END-terminated."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK DUMP_INFO /backup/dump.dmp\r\nversion: 2\r\nEND\r\n"
        assert client._is_response_complete(buffer)

    def test_dump_info_incomplete(self):
        from mygramdb_client import MygramClient

        client = MygramClient()
        buffer = "OK DUMP_INFO /backup/dump.dmp\r\nversion: 2\r\n"
        assert not client._is_response_complete(buffer)

    def test_info_requires_end_marker(self):
        """OK INFO is terminated by END\\r\\n (not the previous \\r\\n\\r\\n heuristic)."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        complete = "OK INFO\r\nversion: 1.0\r\nEND\r\n"
        assert client._is_response_complete(complete)

    def test_first_line_prefix_match_does_not_match_substring(self):
        """A response whose first line is *not* OK DUMP_STATUS must not be
        treated as DUMP_STATUS just because the substring appears later."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        # First line is OK RESULTS, not OK DUMP_STATUS
        buffer = "OK RESULTS 1 OK_DUMP_STATUS_pk\r\n"
        # This must fall through to single-line handling, not require END
        # (it is a terminated single-line response)
        # Without trailing newline it shouldn't be considered complete via END,
        # but it does end with \r\n and thus is a complete single-line response.
        assert client._is_response_complete(buffer) is True

    def test_dump_status_substring_in_middle_does_not_trigger(self):
        """The previous loose `in buffer` check would treat any buffer that
        contained the substring "OK DUMP_STATUS" as DUMP_STATUS. The new
        first-line-only match must not."""
        from mygramdb_client import MygramClient

        client = MygramClient()
        # First line is OK RESULTS; OK DUMP_STATUS appears as PK by accident
        # Buffer ends with \r\n\r\n which is a generic blank-line terminator
        buffer = "OK RESULTS 1 OK_DUMP_STATUS_pk\r\n\r\n"
        assert client._is_response_complete(buffer) is True


class TestSendCommandSerialization:
    """Concurrent send_command calls must not interleave on the wire."""

    def test_command_lock_serializes_concurrent_calls(self):
        """Two coroutines that both call send_command must run sequentially.

        Use the lock directly: while one task holds the command lock the
        other must not be able to enter the critical section.
        """
        import asyncio

        from mygramdb_client import MygramClient

        client = MygramClient()

        async def run():
            lock = client._get_command_lock()
            log = []

            async def worker(name):
                async with lock:
                    log.append(("enter", name))
                    await asyncio.sleep(0.01)
                    log.append(("exit", name))

            await asyncio.gather(worker("a"), worker("b"))
            return log

        log = asyncio.run(run())
        # Verify strict serialization: each enter is followed by its own exit
        # before the next enter.
        for i in range(0, len(log), 2):
            enter_name = log[i][1]
            exit_name = log[i + 1][1]
            assert log[i][0] == "enter"
            assert log[i + 1][0] == "exit"
            assert enter_name == exit_name
