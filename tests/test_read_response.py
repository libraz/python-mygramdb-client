"""Tests for the incremental response reader (chunk-boundary handling)."""
from mygramdb_client import ClientConfig, MygramClient

from .fake_server import FakeMygramServer


async def test_multibyte_snippet_split_across_chunks():
    """
    A multibyte UTF-8 character split across two socket reads must not raise;
    the full response decodes correctly once framing is complete.
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


async def test_large_classic_response_across_chunks():
    """A long single-line SEARCH result spanning many reads parses intact."""
    ids = [f"id{i}" for i in range(500)]
    async with FakeMygramServer() as server:
        server.search_response = (
            "OK RESULTS 500 " + " ".join(ids) + "\r\n"
        ).encode("utf-8")
        client = MygramClient(
            ClientConfig(host=server.host, port=server.port, recv_buffer_size=7)
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
