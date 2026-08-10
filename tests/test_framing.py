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
