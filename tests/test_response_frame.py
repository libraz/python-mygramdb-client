"""Where a response frame ends, decided per command.

Mirrors the C++ client's response-frame tests: the reply is walked line by
line from the context of the request (verb, a real HIGHLIGHT clause, the
connection's DEBUG flag), so a quoted ``highlight`` literal never makes the
reader wait for rows and a failing request ends at its ERROR line.
"""
import asyncio

import pytest

from mygramdb_client import ClientConfig, MygramClient
from mygramdb_client.errors import ServerError
from mygramdb_client.framing import (
    begin_response_frame,
    is_response_complete,
    tokenize_request,
)


def bytes_until_complete(command, wire, debug_mode=False):
    """Feed ``wire`` one byte at a time; return the size when first complete."""
    state = begin_response_frame(command, debug_mode)
    received = bytearray()
    for byte in wire:
        received.append(byte)
        if is_response_complete(received, state):
            return len(received)
    return None


def expect_exact_frame(command, wire, debug_mode=False):
    """A frame must complete exactly at its last byte, byte-wise and in one read."""
    raw = wire.encode("utf-8")
    assert bytes_until_complete(command, raw, debug_mode) == len(raw), (command, wire)
    state = begin_response_frame(command, debug_mode)
    assert is_response_complete(raw, state), (command, wire)


class TestSingleLineReplies:
    @pytest.mark.parametrize(
        "command, wire",
        [
            ("SEARCH t hello", "OK RESULTS 5 pk1 pk2\r\n"),
            ("COUNT t hello", "OK COUNT 42\r\n"),
            ("GET t pk1", "OK DOC pk1 status=active\r\n"),
            ("DUMP LOAD /tmp/x", "OK LOADED /path/to/dump\r\n"),
            ("REPLICATION STOP", "OK REPLICATION_STOPPED\r\n"),
            ("DEBUG ON", "OK DEBUG_ON\r\n"),
            ("SEARCH t hello", "ERROR 4007 Table not found: t\r\n"),
        ],
    )
    def test_ends_at_first_crlf(self, command, wire):
        expect_exact_frame(command, wire)

    def test_incomplete_without_crlf(self):
        state = begin_response_frame("INFO", False)
        assert not is_response_complete(b"", state)
        assert not is_response_complete(b"OK INFO", state)
        assert not is_response_complete(b"OK INFO\r", state)


class TestErrorEndsEveryFramingMode:
    ERROR = "ERROR 4007 Table not found: t\r\n"

    @pytest.mark.parametrize(
        "command, debug",
        [
            ("SEARCH t hello HIGHLIGHT", False),
            ("SEARCH t hello HIGHLIGHT", True),
            ("SEARCH t hello", True),
            ("COUNT t hello", True),
            ("FACET t status", False),
            ("INFO", False),
        ],
    )
    def test_error_line_is_the_whole_frame(self, command, debug):
        expect_exact_frame(command, self.ERROR, debug)

    def test_config_help_error(self):
        expect_exact_frame(
            "CONFIG HELP nope", "ERROR 8 Configuration path not found: nope\r\n"
        )


class TestHighlightDetection:
    @pytest.mark.parametrize(
        "command",
        [
            'SEARCH t "syntax highlight editor"',
            "SEARCH t 'highlight'",
            'SEARCH t "a \\" HIGHLIGHT"',
            'SEARCH t foo FILTER tag = "highlight"',
        ],
    )
    def test_quoted_highlight_literal_does_not_expect_rows(self, command):
        expect_exact_frame(command, "OK RESULTS 0\r\n")

    @pytest.mark.parametrize(
        "command", ['COUNT t "syntax highlight editor"', "COUNT t highlight"]
    )
    def test_count_never_expects_rows(self, command):
        expect_exact_frame(command, "OK COUNT 0\r\n")

    def test_highlight_rows_end_at_trailing_blank_line(self):
        expect_exact_frame(
            "SEARCH t hello HIGHLIGHT",
            "OK RESULTS 1\r\npk1\thello <em>world</em>\r\n\r\n",
        )
        expect_exact_frame(
            "search t hello highlight snippet_len 10",
            "OK RESULTS 1\r\npk1\tx\r\n\r\n",
        )
        expect_exact_frame("SEARCH t hello LIMIT 5 HIGHLIGHT", "OK RESULTS 0\r\n\r\n")

    def test_primary_keys_on_header_mean_a_plain_reply(self):
        expect_exact_frame("SEARCH t hello HIGHLIGHT", "OK RESULTS 2 pk1 pk2\r\n")

    @pytest.mark.parametrize(
        "command",
        [
            "SEARCH t foo AND highlight",
            "SEARCH t foo AND NOT highlight",
            "SEARCH t foo NOT highlight",
            "SEARCH t foo FILTER tag = highlight",
            "SEARCH t foo FILTER tag= highlight",
            'SEARCH t foo FILTER highlight = "x"',
            "SEARCH t foo SORT highlight DESC",
            "SEARCH t foo SORT BY highlight",
            "SEARCH t ( foo OR highlight )",
        ],
    )
    def test_highlight_outside_clause_position_is_an_operand(self, command):
        expect_exact_frame(command, "OK RESULTS 0\r\n")

    @pytest.mark.parametrize(
        "command",
        [
            "SEARCH t foo AND highlight HIGHLIGHT",
            "SEARCH t foo FILTER tag = highlight HIGHLIGHT",
            "SEARCH t foo FILTER tag=x highlight",
            "SEARCH t foo SORT highlight DESC HIGHLIGHT",
            "SEARCH t foo SORT ASC highlight",
            "SEARCH t foo FUZZY highlight",
            "SEARCH t foo FUZZY 2 LIMIT 5 OFFSET 1 highlight",
            "SEARCH t foo OR bar HIGHLIGHT",
        ],
    )
    def test_highlight_clause_after_other_clauses(self, command):
        expect_exact_frame(command, "OK RESULTS 0\r\n\r\n")


class TestDebugBlocks:
    def test_debug_block_ends_at_its_closing_blank_line(self):
        expect_exact_frame(
            "SEARCH t hello",
            "OK RESULTS 2 2 1\r\n\r\n# DEBUG\r\nquery_time: 1.0ms\r\ncache: miss\r\n\r\n",
            debug_mode=True,
        )
        expect_exact_frame(
            "COUNT t hello",
            "OK COUNT 42\r\n\r\n# DEBUG\r\nquery_time: 2.0ms\r\ncache: miss\r\n\r\n",
            debug_mode=True,
        )

    def test_highlight_with_debug_ends_at_third_blank_line(self):
        expect_exact_frame(
            "SEARCH t hello HIGHLIGHT",
            "OK RESULTS 1\r\npk1\tsnip\r\n\r\n# DEBUG\r\nquery_time: 1.0ms\r\n"
            "highlight: on\r\ncache: miss\r\n\r\n\r\n",
            debug_mode=True,
        )
        expect_exact_frame(
            "SEARCH t hello HIGHLIGHT",
            "OK RESULTS 0\r\n\r\n# DEBUG\r\ncache: miss\r\n\r\n\r\n",
            debug_mode=True,
        )


class TestFacet:
    def test_ends_after_body_blank_line_and_transport_crlf(self):
        expect_exact_frame("FACET t status", "OK FACET 2 2\r\nval1\t10\r\nval2\t5\r\n\r\n\r\n")
        expect_exact_frame("FACET t status", "OK FACET 0 0\r\n\r\n\r\n")
        expect_exact_frame(
            "FACET t status",
            "OK FACET 1 1\r\n#x\t3\r\n# query_time_ms: 1.0\r\n\r\n\r\n",
            debug_mode=True,
        )

    def test_header_without_total_ends_at_first_blank_line(self):
        expect_exact_frame("FACET t status", "OK FACET 1\r\nlegacy\t7\r\n\r\n")
        expect_exact_frame("FACET t status", "OK FACET 0\r\n\r\n")


class TestLeadingBlankLine:
    def test_blank_line_from_previous_reply_is_skipped(self):
        expect_exact_frame("COUNT t hello", "\r\nOK COUNT 3\r\n")
        expect_exact_frame(
            "INFO", "\r\nOK INFO\r\n\r\n# Server\r\nversion: 1.0\r\nEND\r\n"
        )

        state = begin_response_frame("COUNT t hello", False)
        assert is_response_complete(b"\r\nOK COUNT 3\r\n", state)
        assert state.frame_start == 2


class TestEndTerminatedBodies:
    def test_end_marker_must_be_a_whole_line(self):
        expect_exact_frame(
            "INFO",
            "OK INFO\r\n\r\n# Server\r\nversion: 1.0\r\n\r\n# Clients\r\n"
            "connected_clients: 1\r\nEND\r\n",
        )
        expect_exact_frame(
            "REPLICATION STATUS",
            "OK REPLICATION\r\nstatus: running\r\nlast_error: xEND\r\nEND\r\n",
        )
        expect_exact_frame(
            "CACHE STATS", "OK CACHE_STATS\r\n\r\n# Cache\r\nenabled: true\r\nEND\r\n"
        )
        expect_exact_frame(
            "DUMP INFO /tmp/snap.bin",
            "OK DUMP_INFO /tmp/snap.bin\r\nversion: 2\r\nEND\r\n",
        )
        expect_exact_frame("DUMP STATUS", "OK DUMP_STATUS\r\nstatus: IDLE\r\nEND\r\n")

    def test_incomplete_without_end_marker(self):
        state = begin_response_frame("DUMP STATUS", False)
        assert not is_response_complete(b"OK DUMP_STATUS\r\nstatus: saving\r\n", state)

    def test_sync_status_includes_blank_line_after_end(self):
        expect_exact_frame(
            "SYNC STATUS",
            'OK SYNC_STATUS\r\nstatus=IDLE message="No sync operation performed"\r\nEND\r\n\r\n',
        )
        expect_exact_frame(
            "SYNC STATUS",
            "OK SYNC_STATUS\r\ntable=users status=IN_PROGRESS\r\nEND\r\n\r\n",
        )

    def test_substring_of_a_status_line_in_a_primary_key_is_a_plain_reply(self):
        expect_exact_frame("SEARCH t x", "OK RESULTS 1 OK_DUMP_STATUS_pk\r\n")


class TestPlusOkBodies:
    def test_config_help_body_keeps_its_internal_blank_line(self):
        expect_exact_frame(
            "CONFIG HELP mysql.port",
            "+OK\r\nmysql.port\r\n\r\nType: integer\r\nDefault: 3306\r\n"
            "Description: MySQL port\r\n\r\n",
        )
        expect_exact_frame(
            "config  help",
            "+OK\r\nAvailable configuration sections:\r\n  mysql - MySQL\r\n\r\n"
            'Use "CONFIG HELP <section>" for detailed information.\r\n\r\n',
        )

    def test_other_bodies_end_at_first_blank_line(self):
        expect_exact_frame("CONFIG", "+OK\r\nmysql:\r\n  host: localhost\r\n\r\n")
        expect_exact_frame("CONFIG SHOW tables", "+OK\r\n\r\n\r\n")
        expect_exact_frame(
            "CONFIG VERIFY a.yaml",
            "+OK\r\nConfiguration is valid\r\n  Tables: 1 (t)\r\n  MySQL: h:3306\r\n\r\n",
        )
        expect_exact_frame("SET a = b", "+OK Variable 'a' set to 'b'\r\n\r\n")
        expect_exact_frame("SHOW VARIABLES LIKE 'x%'", "+OK 0 rows\r\n\r\n")
        expect_exact_frame(
            "SHOW VARIABLES",
            "+------+\r\n| Variable_name | Value | Mutable |\r\n+------+\r\n"
            "| a | b | YES |\r\n+------+\r\n1 row in set\r\n\r\n",
        )


class TestTokenizeRequest:
    def test_follows_server_splitting_rules(self):
        tokens = tokenize_request('dump　load  \'a b\'"c"d "e\\" f"')
        assert [(t.text, t.quoted) for t in tokens] == [
            ("dump", False),
            ("load", False),
            ("a b", True),
            ("c", True),
            ("d", False),
            ('e\\" f', True),
        ]

    def test_nel_splits_and_zero_width_space_does_not(self):
        assert [t.text for t in tokenize_request("a\u0085b")] == ["a", "b"]
        assert [t.text for t in tokenize_request("a​b")] == ["a​b"]


async def _serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


class TestClientReadsPerCommandFrames:
    """The read loop applies the frame grammar against a real socket."""

    async def _client_for(self, replies):
        """A server answering each request line with the next canned reply."""
        seen = []
        queue = list(replies)

        async def handle(reader, writer):
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    seen.append(line.decode("utf-8").rstrip("\r\n"))
                    writer.write(queue.pop(0))
                    await writer.drain()
            finally:
                writer.close()

        server, port = await _serve(handle)
        client = MygramClient(ClientConfig(host="127.0.0.1", port=port, timeout=1.0))
        await client.connect()
        return server, client, seen

    async def test_failing_highlighted_search_returns_its_error_at_once(self):
        server, client, _ = await self._client_for(
            [b"ERROR 4000 Query term is too short\r\n"]
        )
        try:
            with pytest.raises(ServerError) as excinfo:
                await client.send_command("SEARCH t hello HIGHLIGHT")
            assert excinfo.value.error_code == 4000
        finally:
            await client.disconnect()
            server.close()

    async def test_quoted_highlight_term_does_not_hang(self):
        server, client, _ = await self._client_for([b"OK RESULTS 1 pk1\r\n"])
        try:
            response = await client.send_command('SEARCH t "syntax highlight editor"')
            assert response == "OK RESULTS 1 pk1"
        finally:
            await client.disconnect()
            server.close()

    async def test_raw_debug_commands_drive_the_debug_framing(self):
        debug_reply = (
            b"OK RESULTS 1 pk1\r\n\r\n# DEBUG\r\nquery_time: 1.0ms\r\n"
            b"cache: miss\r\n\r\n"
        )
        server, client, _ = await self._client_for(
            [b"OK DEBUG_ON\r\n", debug_reply, b"OK DEBUG_OFF\r\n", b"OK RESULTS 1 pk1\r\n"]
        )
        try:
            await client.send_command("debug on")
            assert client._debug_mode is True
            response = await client.send_command("SEARCH t hello")
            assert "# DEBUG" in response
            await client.send_command("DEBUG OFF")
            assert client._debug_mode is False
            assert await client.send_command("SEARCH t hello") == "OK RESULTS 1 pk1"
        finally:
            await client.disconnect()
            server.close()

    async def test_debug_flag_dies_with_the_connection(self):
        server, client, _ = await self._client_for([b"OK DEBUG_ON\r\n"])
        try:
            await client.send_command("DEBUG ON")
            assert client._debug_mode is True
            await client.disconnect()
            assert client._debug_mode is False
        finally:
            server.close()

    async def test_trailing_crlf_after_a_legacy_facet_reply_is_skipped_by_the_next_reply(self):
        server, client, _ = await self._client_for(
            [b"OK FACET 1\r\nlegacy\t7\r\n\r\n", b"\r\nOK COUNT 3\r\n"]
        )
        try:
            first = await client.send_command("FACET t status")
            assert first.startswith("OK FACET 1")
            assert await client.send_command("COUNT t hello") == "OK COUNT 3"
        finally:
            await client.disconnect()
            server.close()
