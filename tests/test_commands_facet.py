"""The FACET surface: command construction and response parsing.

FACET keeps its request and response together because they are one contract —
the header carries the pagination counterpart of the OFFSET/LIMIT clause sent
with the request.
"""
import pytest

from mygramdb_client import (
    FacetOptions,
    FacetResponse,
    FacetValue,
    FilterCondition,
    FilterOp,
    MygramClient,
)
from mygramdb_client.errors import ProtocolError

from .command_capture import capture_command


async def build_facet_command(table: str, column: str, opts: FacetOptions) -> str:
    return await capture_command(lambda client: client.facet(table, column, opts))


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


class TestFacetCommand:
    async def test_facet_no_query(self):
        cmd = await build_facet_command("articles", "category", FacetOptions())
        assert cmd == "FACET articles category"

    async def test_facet_with_query(self):
        # The search text follows the column directly — FACET has no keyword
        # introducing it, so a "QUERY" token would be read as search text.
        cmd = await build_facet_command(
            "articles", "category", FacetOptions(query="python"),
        )
        assert cmd == "FACET articles category python"

    async def test_facet_with_query_and_and_terms(self):
        cmd = await build_facet_command(
            "articles", "category",
            FacetOptions(query="python", and_terms=["tutorial"]),
        )
        assert cmd == "FACET articles category python AND tutorial"

    async def test_facet_with_query_and_not_terms(self):
        cmd = await build_facet_command(
            "articles", "category",
            FacetOptions(query="python", not_terms=["draft"]),
        )
        assert cmd == "FACET articles category python NOT draft"

    async def test_facet_with_query_and_filters(self):
        cmd = await build_facet_command(
            "articles", "category",
            FacetOptions(query="python", filters={"status": "published"}),
        )
        assert cmd == "FACET articles category python FILTER status = published"

    async def test_facet_emits_operator_filters(self):
        cmd = await build_facet_command(
            "articles", "category",
            FacetOptions(
                query="python",
                filter_conditions=[FilterCondition("views", "10", FilterOp.LTE)],
            ),
        )
        assert cmd == "FACET articles category python FILTER views <= 10"

    async def test_facet_refinements_apply_without_a_query(self):
        # A whole-table facet still accepts AND/NOT/FILTER refinements.
        cmd = await build_facet_command(
            "articles", "category",
            FacetOptions(and_terms=["tutorial"], not_terms=["draft"],
                         filters={"status": "published"}),
        )
        assert cmd == (
            "FACET articles category AND tutorial NOT draft "
            "FILTER status = published"
        )


class TestFacetPaginationCommand:
    """OFFSET / LIMIT on the request (v1.9+)."""

    async def test_facet_with_limit(self):
        cmd = await build_facet_command(
            "articles", "category", FacetOptions(limit=10),
        )
        assert cmd == "FACET articles category LIMIT 10"

    async def test_offset_and_limit_are_sent(self):
        cmd = await build_facet_command(
            "articles", "category", FacetOptions(limit=10, offset=20),
        )
        assert cmd == "FACET articles category LIMIT 20,10"

    async def test_offset_without_limit_is_sent_bare(self):
        cmd = await build_facet_command(
            "articles", "category", FacetOptions(offset=20),
        )
        assert cmd == "FACET articles category OFFSET 20"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestFacetResponseParsing:
    def test_parse_basic_facet_response(self):
        response = (
            "OK FACET 3\n"
            "python\t42\n"
            "rust\t17\n"
            "go\t8"
        )
        result = MygramClient._parse_facet_response(response)

        assert isinstance(result, FacetResponse)
        assert len(result.results) == 3
        assert result.results[0] == FacetValue(value="python", count=42)
        assert result.results[1] == FacetValue(value="rust", count=17)
        assert result.results[2] == FacetValue(value="go", count=8)

    def test_parse_empty_facet_response(self):
        result = MygramClient._parse_facet_response("OK FACET 0")

        assert len(result.results) == 0

    def test_parse_facet_with_comments(self):
        response = (
            "OK FACET 2\n"
            "# some comment\n"
            "a\t1\n"
            "b\t2"
        )
        result = MygramClient._parse_facet_response(response)

        assert len(result.results) == 2
        assert result.results[0].value == "a"
        assert result.results[1].value == "b"

    def test_parse_facet_with_trailing_blank(self):
        result = MygramClient._parse_facet_response("OK FACET 1\nx\t5\n")

        assert len(result.results) == 1
        assert result.results[0] == FacetValue(value="x", count=5)

    def test_value_with_spaces_preserved(self):
        """Facet values may contain arbitrary characters (including spaces)."""
        result = MygramClient._parse_facet_response("OK FACET 1\nhello world\t5")

        assert result.results[0].value == "hello world"
        assert result.results[0].count == 5

    def test_value_starting_with_hash_is_kept(self):
        # Only a tab-less "#" line is a comment, so a legitimate "#tag" value —
        # which carries a tab before its count — survives (v1.8+).
        response = "OK FACET 2\n#special\t5\nnormal\t3"
        result = MygramClient._parse_facet_response(response)

        by_value = {v.value: v.count for v in result.results}
        assert by_value == {"#special": 5, "normal": 3}

    def test_comment_line_without_tab_is_skipped(self):
        response = "OK FACET 1\n# a comment line\nvalue\t7"
        result = MygramClient._parse_facet_response(response)

        assert len(result.results) == 1
        assert result.results[0].value == "value"
        assert result.results[0].count == 7

    def test_invalid_header_rejected(self):
        with pytest.raises(ProtocolError, match="Invalid FACET response"):
            MygramClient._parse_facet_response("BOGUS")

    def test_missing_count_rejected(self):
        with pytest.raises(ProtocolError, match="missing count"):
            MygramClient._parse_facet_response("OK FACET")

    def test_non_numeric_count_rejected(self):
        with pytest.raises(ProtocolError, match="Invalid FACET count"):
            MygramClient._parse_facet_response("OK FACET xyz")

    def test_row_without_tab_rejected(self):
        with pytest.raises(ProtocolError, match="Invalid FACET row"):
            MygramClient._parse_facet_response("OK FACET 1\nno_tab_here")

    def test_row_with_non_numeric_count_rejected(self):
        with pytest.raises(ProtocolError, match="Invalid FACET count for a"):
            MygramClient._parse_facet_response("OK FACET 1\na\tnotanumber")


class TestFacetPaginationResponse:
    """The distinct value total alongside the returned page (v1.9+)."""

    def test_total_count_read_from_header(self):
        response = "OK FACET 2 57\nalpha\t5\nbeta\t3"
        result = MygramClient._parse_facet_response(response)

        assert len(result.results) == 2
        assert result.total_count == 57

    def test_total_count_falls_back_to_page_size_on_older_server(self):
        # A pre-v1.9 server emits only the page size; the total mirrors it
        # rather than reporting zero, which would read as "no values at all".
        response = "OK FACET 2\nalpha\t5\nbeta\t3"
        result = MygramClient._parse_facet_response(response)

        assert result.total_count == 2

    def test_non_numeric_total_is_rejected(self):
        with pytest.raises(ProtocolError, match="Invalid FACET total count"):
            MygramClient._parse_facet_response("OK FACET 1 many\nalpha\t5")
