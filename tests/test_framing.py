"""Response framing: where a response ends, and the bounds on reading it.

Three related concerns, all about the read loop rather than about any one
command: deciding a buffer holds a complete response, reassembling one that
arrives in pieces, and refusing one that never ends.
"""
import asyncio

import pytest

from mygramdb_client import ClientConfig, MygramClient
from mygramdb_client.errors import ProtocolError, TimeoutError

from .fake_server import FakeMygramServer


class TestMultiLineCompletionDetection:
    """Tab-separated FACET and highlighted SEARCH bodies end on a blank line."""

    def test_facet_response_incomplete(self):
        client = MygramClient()
        assert not client._is_response_complete("OK FACET 2\nvalue1\t5")

    def test_facet_response_complete_lf(self):
        client = MygramClient()
        buffer = "OK FACET 2\nvalue1\t5\nvalue2\t3\n\n"
        assert client._is_response_complete(buffer)

    def test_facet_response_complete_crlf(self):
        client = MygramClient()
        buffer = "OK FACET 2\r\nvalue1\t5\r\nvalue2\t3\r\n\r\n"
        assert client._is_response_complete(buffer)

    def test_facet_empty_complete(self):
        client = MygramClient()
        assert client._is_response_complete("OK FACET 0\n\n")

    def test_highlight_response_incomplete(self):
        client = MygramClient()
        assert not client._is_response_complete("OK RESULTS 2\nid1\tsnippet1")

    def test_highlight_response_complete(self):
        client = MygramClient()
        buffer = "OK RESULTS 2\nid1\tsnippet1\nid2\tsnippet2\n\n"
        assert client._is_response_complete(buffer)

    def test_classic_search_response_still_complete(self):
        """Regression: single-line SEARCH response should still terminate on \\n."""
        client = MygramClient()
        assert client._is_response_complete("OK RESULTS 2 id1 id2\n")


class TestSyncStatusFraming:
    """_is_response_complete treats OK SYNC_STATUS as END-terminated."""

    def test_incomplete_without_end_marker(self):
        client = MygramClient()
        assert not client._is_response_complete("OK SYNC_STATUS\r\n")
        assert not client._is_response_complete(
            "OK SYNC_STATUS\r\nstatus=IDLE\r\n"
        )

    def test_complete_with_end_marker(self):
        client = MygramClient()
        assert client._is_response_complete(
            "OK SYNC_STATUS\r\nstatus=IDLE\r\nEND\r\n"
        )

    def test_complete_with_trailing_blank_line_after_end(self):
        # The server appends a trailing blank line after END for SYNC_STATUS.
        client = MygramClient()
        assert client._is_response_complete(
            'OK SYNC_STATUS\r\nstatus=IDLE message="x"\r\nEND\r\n\r\n'
        )


class TestChunkBoundaryReassembly:
    """A response split across socket reads is reassembled intact."""

    async def test_multibyte_snippet_split_across_chunks(self):
        """
        A multibyte UTF-8 character split across two socket reads must not
        raise; the full response decodes correctly once framing is complete.
        """
        snippet = "日本語のハイライト表示"
        async with FakeMygramServer() as server:
            server.search_response = (
                "OK RESULTS 1\r\npk1\t" + snippet + "\r\n\r\n"
            ).encode("utf-8")
            client = MygramClient(
                ClientConfig(
                    host=server.host,
                    port=server.port,
                    # Tiny reads guarantee a multibyte character straddles a chunk.
                    recv_buffer_size=3,
                )
            )
            await client.connect()
            try:
                result = await client.search_with_highlights("articles", "x")
                assert result.total_count == 1
                assert result.results[0].primary_key == "pk1"
                assert result.results[0].snippet == snippet
            finally:
                await client.disconnect()

    async def test_large_classic_response_across_chunks(self):
        """A long single-line SEARCH result spanning many reads parses intact."""
        ids = [f"id{i}" for i in range(500)]
        async with FakeMygramServer() as server:
            server.search_response = (
                "OK RESULTS 500 " + " ".join(ids) + "\r\n"
            ).encode("utf-8")
            client = MygramClient(
                ClientConfig(
                    host=server.host, port=server.port, recv_buffer_size=7
                )
            )
            await client.connect()
            try:
                result = await client.search("articles", "x")
                assert result.total_count == 500
                assert len(result.results) == 500
                assert result.results[0].primary_key == "id0"
                assert result.results[-1].primary_key == "id499"
            finally:
                await client.disconnect()


class TestDebugAndHighlightChunkedDelivery:
    """
    A HIGHLIGHT+DEBUG response delivered in separate chunks must not be
    mistaken for complete at either chunk boundary: right after the header
    (before the highlight rows and debug block arrive), and right after the
    debug block's own opening blank line (before "# DEBUG" itself arrives,
    which by itself looks like a "blank line" terminator).
    """

    async def test_highlight_with_debug_split_before_debug_marker(self):
        async def handle(reader, writer):
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    command = line.decode("utf-8").strip()
                    if command.upper() == "DEBUG ON":
                        writer.write(b"OK DEBUG_ON\r\n")
                        await writer.drain()
                        continue
                    if command.upper().startswith("SEARCH"):
                        # First chunk ends right after the blank line that
                        # opens the debug block -- before "# DEBUG" itself
                        # arrives. This is the exact byte pattern a naive
                        # "ends with a blank line" check mistakes for the
                        # frame's real end.
                        writer.write(b"OK RESULTS 1\r\npk1\thello <em>x</em>\r\n\r\n")
                        await writer.drain()
                        await asyncio.sleep(0.05)
                        writer.write(
                            b"# DEBUG\r\n"
                            b"query_time: 1.5ms\r\n"
                            b"index_time: 0.5ms\r\n"
                            b"terms: 1\r\n"
                            b"ngrams: 2\r\n"
                            b"final: 1\r\n"
                            b"cache: miss\r\n"
                            b"\r\n"
                        )
                        await writer.drain()
                        continue
                    writer.write(b"ERROR unknown command\r\n")
                    await writer.drain()
            finally:
                # Closing the server-side transport on EOF (matching
                # FakeMygramServer) lets asyncio.Server.wait_closed() below
                # resolve once the client disconnects.
                try:
                    writer.close()
                except Exception:
                    pass

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            client = MygramClient(ClientConfig(host="127.0.0.1", port=port))
            await client.connect()
            try:
                await client.enable_debug()
                result = await client.search_with_highlights("articles", "x")
                assert result.total_count == 1
                assert result.results[0].primary_key == "pk1"
                assert result.results[0].snippet == "hello <em>x</em>"
                # If the client had stopped reading at the first chunk, the
                # debug block would never have been parsed.
                assert result.debug is not None
                assert result.debug.query_time_ms == 1.5
                assert result.debug.terms == 1
            finally:
                await client.disconnect()
        finally:
            server.close()
            await server.wait_closed()

    async def test_classic_search_with_debug_split_at_header(self):
        async def handle(reader, writer):
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    command = line.decode("utf-8").strip()
                    if command.upper() == "DEBUG ON":
                        writer.write(b"OK DEBUG_ON\r\n")
                        await writer.drain()
                        continue
                    if command.upper().startswith("SEARCH"):
                        # First chunk is exactly the classic header line --
                        # looks like a complete single-line response unless
                        # the client knows debug mode means a tail is still
                        # coming.
                        writer.write(b"OK RESULTS 1 pk1")
                        await writer.drain()
                        await asyncio.sleep(0.05)
                        writer.write(
                            b"\r\n\r\n# DEBUG\r\n"
                            b"query_time: 2.0ms\r\n"
                            b"index_time: 1.0ms\r\n"
                            b"terms: 1\r\n"
                            b"ngrams: 2\r\n"
                            b"final: 1\r\n"
                            b"cache: miss\r\n"
                            b"\r\n"
                        )
                        await writer.drain()
                        continue
                    writer.write(b"ERROR unknown command\r\n")
                    await writer.drain()
            finally:
                try:
                    writer.close()
                except Exception:
                    pass

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            client = MygramClient(ClientConfig(host="127.0.0.1", port=port))
            await client.connect()
            try:
                await client.enable_debug()
                result = await client.search("articles", "x")
                assert result.total_count == 1
                assert result.results[0].primary_key == "pk1"
                assert result.debug is not None
                assert result.debug.query_time_ms == 2.0
            finally:
                await client.disconnect()
        finally:
            server.close()
            await server.wait_closed()


class TestIPv6Connectivity:
    """A server reachable only via an IPv6 literal is reachable (v1.10.2)."""

    async def test_connect_and_round_trip_over_ipv6_loopback(self):
        async with FakeMygramServer(host="::1") as server:
            client = MygramClient(ClientConfig(host=server.host, port=server.port))
            await client.connect()
            try:
                assert client.is_connected()
                result = await client.search("articles", "x")
                assert result.total_count == 1
                assert result.results[0].primary_key == "pk1"
            finally:
                await client.disconnect()


class TestResponseBounds:
    """A response that never completes must not hold the command open (v1.10+)."""

    async def test_total_deadline_is_not_reset_by_partial_reads(self):
        # A server that dribbles bytes forever used to keep the command alive
        # indefinitely, because each partial read restarted the timer.
        async def trickle(reader, writer):
            await reader.readline()
            try:
                while True:
                    writer.write(b"x")
                    await writer.drain()
                    await asyncio.sleep(0.01)
            except (ConnectionResetError, BrokenPipeError):
                pass

        server = await asyncio.start_server(trickle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            client = MygramClient(
                ClientConfig(host="127.0.0.1", port=port, timeout=0.2)
            )
            await client.connect()
            try:
                start = asyncio.get_event_loop().time()
                with pytest.raises(TimeoutError):
                    await client.send_command("INFO")
                elapsed = asyncio.get_event_loop().time() - start
            finally:
                await client.disconnect()
        finally:
            server.close()
            await server.wait_closed()

        # Comfortably below the point a per-read timer would have reached.
        assert elapsed < 1.0

    async def test_oversized_response_is_rejected_and_connection_dropped(self):
        async def flood(reader, writer):
            await reader.readline()
            try:
                for _ in range(64):
                    writer.write(b"x" * 4096)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                pass

        server = await asyncio.start_server(flood, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            client = MygramClient(
                ClientConfig(
                    host="127.0.0.1",
                    port=port,
                    timeout=2.0,
                    max_response_bytes=8192,
                )
            )
            await client.connect()
            try:
                with pytest.raises(ProtocolError, match="max_response_bytes"):
                    await client.send_command("INFO")
                assert not client.is_connected()
            finally:
                await client.disconnect()
        finally:
            server.close()
            await server.wait_closed()
