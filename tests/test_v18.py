"""Unit tests for MygramDB v1.8 client-alignment changes.

Covers the two wire-level changes required for v1.8 parity:

- ``search_raw`` sends the boolean expression verbatim (unquoted) so the server
  can tokenize AND/OR/NOT and grouping, including OR groups nested under AND.
- ``FACET`` rows whose value starts with ``#`` are kept (only tab-less ``#``
  comment lines are skipped).
"""
import pytest

from mygramdb_client import (
    ClientConfig,
    FacetResponse,
    MygramClient,
    SearchRawOptions,
)
from mygramdb_client.errors import ProtocolError

from .fake_server import FakeMygramServer


class TestSearchRawUnquotedTransport:
    async def test_grouped_expression_sent_verbatim(self):
        async with FakeMygramServer() as server:
            client = MygramClient(
                ClientConfig(host=server.host, port=server.port)
            )
            await client.connect()
            try:
                await client.search_raw(
                    "articles",
                    "(ruby OR python) AND machine",
                    SearchRawOptions(limit=5),
                )
            finally:
                await client.disconnect()

        assert server.commands[-1] == (
            "SEARCH articles (ruby OR python) AND machine LIMIT 5"
        )

    async def test_plain_search_still_quotes_query(self):
        # search() must keep auto-quoting literal text; only search_raw changed.
        async with FakeMygramServer() as server:
            client = MygramClient(
                ClientConfig(host=server.host, port=server.port)
            )
            await client.connect()
            try:
                await client.search_raw("articles", "alpha OR beta")
                await client.search("articles", "hello world")
            finally:
                await client.disconnect()

        raw_cmd = server.commands[0]
        plain_cmd = server.commands[1]
        assert raw_cmd == "SEARCH articles alpha OR beta"
        # The literal query is quoted because it contains whitespace.
        assert '"hello world"' in plain_cmd


class TestFacetHashValueParsing:
    def test_value_starting_with_hash_is_kept(self):
        response = "OK FACET 2\n#special\t5\nnormal\t3"
        result = MygramClient._parse_facet_response(response)

        assert isinstance(result, FacetResponse)
        by_value = {v.value: v.count for v in result.results}
        assert by_value == {"#special": 5, "normal": 3}

    def test_comment_line_without_tab_is_skipped(self):
        response = "OK FACET 1\n# a comment line\nvalue\t7"
        result = MygramClient._parse_facet_response(response)

        assert len(result.results) == 1
        assert result.results[0].value == "value"
        assert result.results[0].count == 7

    def test_malformed_row_still_raises(self):
        response = "OK FACET 1\nno_tab_here"
        with pytest.raises(ProtocolError, match="Invalid FACET row"):
            MygramClient._parse_facet_response(response)
