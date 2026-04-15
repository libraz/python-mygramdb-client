"""
Tests for MygramDB v1.6 protocol features:
- FUZZY search (Levenshtein edit distance)
- HIGHLIGHT clause (snippet generation)
- FACET aggregation
- BM25 relevance scoring via ``_score`` sort column
"""
import pytest

from mygramdb_client import (
    FacetOptions,
    FacetResponse,
    FacetValue,
    HighlightOptions,
    MygramClient,
    SearchOptions,
)
from mygramdb_client.command_utils import (
    validate_facet_column,
    validate_fuzzy,
    validate_highlight,
)
from mygramdb_client.errors import InputValidationError, ProtocolError


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


class TestValidateFuzzy:
    """Tests for validate_fuzzy."""

    def test_zero_is_valid(self):
        validate_fuzzy(0)

    def test_one_is_valid(self):
        validate_fuzzy(1)

    def test_two_is_valid(self):
        validate_fuzzy(2)

    def test_three_rejected(self):
        with pytest.raises(InputValidationError, match="must be 0, 1, or 2"):
            validate_fuzzy(3)

    def test_negative_rejected(self):
        with pytest.raises(InputValidationError):
            validate_fuzzy(-1)


class TestValidateHighlight:
    """Tests for validate_highlight."""

    def test_none_is_valid(self):
        validate_highlight(None)

    def test_empty_options_valid(self):
        validate_highlight(HighlightOptions())

    def test_paired_tags_valid(self):
        validate_highlight(HighlightOptions(open_tag="<em>", close_tag="</em>"))

    def test_open_without_close_rejected(self):
        with pytest.raises(InputValidationError, match="set together"):
            validate_highlight(HighlightOptions(open_tag="<em>"))

    def test_close_without_open_rejected(self):
        with pytest.raises(InputValidationError, match="set together"):
            validate_highlight(HighlightOptions(close_tag="</em>"))

    def test_tag_with_space_rejected(self):
        with pytest.raises(InputValidationError, match="whitespace"):
            validate_highlight(HighlightOptions(open_tag="<em >", close_tag="</em>"))

    def test_tag_with_tab_rejected(self):
        # Tab (0x09) is a control character, caught before the whitespace check.
        with pytest.raises(InputValidationError):
            validate_highlight(HighlightOptions(open_tag="<em\t>", close_tag="</em>"))

    def test_tag_with_control_char_rejected(self):
        with pytest.raises(InputValidationError):
            validate_highlight(HighlightOptions(open_tag="<em\n>", close_tag="</em>"))

    def test_snippet_len_in_range_valid(self):
        validate_highlight(HighlightOptions(snippet_len=500))

    def test_snippet_len_zero_valid(self):
        validate_highlight(HighlightOptions(snippet_len=0))

    def test_snippet_len_negative_rejected(self):
        with pytest.raises(InputValidationError, match="snippet_len"):
            validate_highlight(HighlightOptions(snippet_len=-1))

    def test_snippet_len_too_large_rejected(self):
        with pytest.raises(InputValidationError, match="snippet_len"):
            validate_highlight(HighlightOptions(snippet_len=10001))

    def test_max_fragments_in_range_valid(self):
        validate_highlight(HighlightOptions(max_fragments=5))

    def test_max_fragments_too_large_rejected(self):
        with pytest.raises(InputValidationError, match="max_fragments"):
            validate_highlight(HighlightOptions(max_fragments=101))

    def test_max_fragments_negative_rejected(self):
        with pytest.raises(InputValidationError, match="max_fragments"):
            validate_highlight(HighlightOptions(max_fragments=-1))


class TestValidateFacetColumn:
    """Tests for validate_facet_column."""

    def test_valid_column(self):
        validate_facet_column("category")

    def test_empty_column_rejected(self):
        with pytest.raises(InputValidationError, match="must not be empty"):
            validate_facet_column("")

    def test_space_rejected(self):
        with pytest.raises(InputValidationError, match="invalid character"):
            validate_facet_column("bad column")

    def test_tab_rejected(self):
        with pytest.raises(InputValidationError, match="invalid character"):
            validate_facet_column("bad\tcol")

    def test_control_char_rejected(self):
        with pytest.raises(InputValidationError, match="invalid character"):
            validate_facet_column("bad\x00col")

    def test_delete_rejected(self):
        with pytest.raises(InputValidationError, match="invalid character"):
            validate_facet_column("bad\x7fcol")


# ---------------------------------------------------------------------------
# Command formatting (builds SEARCH/FACET without a real socket)
# ---------------------------------------------------------------------------


def build_search_command(table: str, query: str, opts: SearchOptions) -> str:
    """Mimic MygramClient.search command construction for inspection."""
    parts = ["SEARCH", table, query]
    for term in opts.and_terms:
        parts.extend(["AND", term])
    for term in opts.not_terms:
        parts.extend(["NOT", term])
    for key, value in opts.filters.items():
        parts.extend(["FILTER", key, "=", value])
    if opts.sort_column:
        parts.extend(["SORT", opts.sort_column, "DESC" if opts.sort_desc else "ASC"])
    if opts.fuzzy > 0:
        parts.extend(["FUZZY", str(opts.fuzzy)])
    if opts.highlight is not None:
        parts.append("HIGHLIGHT")
        if opts.highlight.open_tag and opts.highlight.close_tag:
            parts.extend(["TAG", opts.highlight.open_tag, opts.highlight.close_tag])
        if opts.highlight.snippet_len and opts.highlight.snippet_len > 0:
            parts.extend(["SNIPPET_LEN", str(opts.highlight.snippet_len)])
        if opts.highlight.max_fragments and opts.highlight.max_fragments > 0:
            parts.extend(["MAX_FRAGMENTS", str(opts.highlight.max_fragments)])
    if opts.offset > 0:
        parts.extend(["LIMIT", f"{opts.offset},{opts.limit}"])
    else:
        parts.extend(["LIMIT", str(opts.limit)])
    return " ".join(parts)


class TestFuzzyCommand:
    """Tests for FUZZY clause emission."""

    def test_fuzzy_zero_omits_clause(self):
        cmd = build_search_command("articles", "hello", SearchOptions(fuzzy=0))
        assert "FUZZY" not in cmd

    def test_fuzzy_one(self):
        cmd = build_search_command("articles", "hello", SearchOptions(fuzzy=1))
        assert "FUZZY 1" in cmd

    def test_fuzzy_two(self):
        cmd = build_search_command("articles", "hello", SearchOptions(fuzzy=2))
        assert "FUZZY 2" in cmd

    def test_fuzzy_appears_after_sort(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(fuzzy=1, sort_column="id"),
        )
        sort_idx = cmd.index("SORT")
        fuzzy_idx = cmd.index("FUZZY")
        assert sort_idx < fuzzy_idx


class TestHighlightCommand:
    """Tests for HIGHLIGHT clause emission."""

    def test_highlight_default(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions()),
        )
        assert "HIGHLIGHT" in cmd
        assert "TAG" not in cmd
        assert "SNIPPET_LEN" not in cmd
        assert "MAX_FRAGMENTS" not in cmd

    def test_highlight_with_custom_tags(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(
                open_tag="<b>", close_tag="</b>",
            )),
        )
        assert "HIGHLIGHT TAG <b> </b>" in cmd

    def test_highlight_with_snippet_len(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(snippet_len=200)),
        )
        assert "SNIPPET_LEN 200" in cmd

    def test_highlight_with_max_fragments(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(max_fragments=5)),
        )
        assert "MAX_FRAGMENTS 5" in cmd

    def test_highlight_full_options(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(
                open_tag="<mark>",
                close_tag="</mark>",
                snippet_len=150,
                max_fragments=3,
            )),
        )
        assert "HIGHLIGHT TAG <mark> </mark> SNIPPET_LEN 150 MAX_FRAGMENTS 3" in cmd

    def test_highlight_appears_after_fuzzy(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(fuzzy=1, highlight=HighlightOptions()),
        )
        fuzzy_idx = cmd.index("FUZZY")
        hl_idx = cmd.index("HIGHLIGHT")
        assert fuzzy_idx < hl_idx

    def test_highlight_before_limit(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions()),
        )
        hl_idx = cmd.index("HIGHLIGHT")
        limit_idx = cmd.index("LIMIT")
        assert hl_idx < limit_idx


class TestScoreSort:
    """Tests for BM25 scoring via _score sort column."""

    def test_score_sort_desc(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(sort_column="_score", sort_desc=True),
        )
        assert "SORT _score DESC" in cmd

    def test_score_sort_asc(self):
        cmd = build_search_command(
            "articles", "hello",
            SearchOptions(sort_column="_score", sort_desc=False),
        )
        assert "SORT _score ASC" in cmd


def build_facet_command(table: str, column: str, opts: FacetOptions) -> str:
    """Mimic MygramClient.facet command construction for inspection."""
    parts = ["FACET", table, column]
    if opts.query:
        parts.extend(["QUERY", opts.query])
        for term in opts.and_terms:
            parts.extend(["AND", term])
        for term in opts.not_terms:
            parts.extend(["NOT", term])
        for key, value in opts.filters.items():
            parts.extend(["FILTER", key, "=", value])
    if opts.limit > 0:
        parts.extend(["LIMIT", str(opts.limit)])
    return " ".join(parts)


class TestFacetCommand:
    """Tests for FACET command emission."""

    def test_facet_no_query(self):
        cmd = build_facet_command("articles", "category", FacetOptions())
        assert cmd == "FACET articles category"

    def test_facet_with_query(self):
        cmd = build_facet_command(
            "articles", "category",
            FacetOptions(query="python"),
        )
        assert cmd == "FACET articles category QUERY python"

    def test_facet_with_query_and_and_terms(self):
        cmd = build_facet_command(
            "articles", "category",
            FacetOptions(query="python", and_terms=["tutorial"]),
        )
        assert cmd == "FACET articles category QUERY python AND tutorial"

    def test_facet_with_query_and_not_terms(self):
        cmd = build_facet_command(
            "articles", "category",
            FacetOptions(query="python", not_terms=["draft"]),
        )
        assert cmd == "FACET articles category QUERY python NOT draft"

    def test_facet_with_query_and_filters(self):
        cmd = build_facet_command(
            "articles", "category",
            FacetOptions(query="python", filters={"status": "published"}),
        )
        assert cmd == "FACET articles category QUERY python FILTER status = published"

    def test_facet_with_limit(self):
        cmd = build_facet_command(
            "articles", "category",
            FacetOptions(limit=10),
        )
        assert cmd == "FACET articles category LIMIT 10"

    def test_facet_and_not_filter_only_apply_when_query_present(self):
        cmd = build_facet_command(
            "articles", "category",
            FacetOptions(and_terms=["ignored"], not_terms=["ignored"],
                         filters={"k": "v"}),
        )
        # Without QUERY, AND/NOT/FILTER should be skipped
        assert cmd == "FACET articles category"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestHighlightSearchResponse:
    """Tests for parsing HIGHLIGHT multi-line SEARCH responses."""

    def test_parse_multiline_highlight_response(self):
        response = (
            "OK RESULTS 2\n"
            "id1\tHello <em>world</em>\n"
            "id2\tGoodbye <em>world</em>"
        )
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 2
        assert len(result.results) == 2
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == "Hello <em>world</em>"
        assert result.results[1].primary_key == "id2"
        assert result.results[1].snippet == "Goodbye <em>world</em>"

    def test_parse_highlight_with_empty_snippet(self):
        response = "OK RESULTS 1\nid1\t"
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 1
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == ""

    def test_parse_highlight_without_tab_treated_as_pk(self):
        """A payload line without a tab should be treated as a bare PK."""
        response = "OK RESULTS 1\nid1"
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 1
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == ""

    def test_classic_single_line_still_works(self):
        """Regression test: classic SEARCH response must still parse."""
        response = "OK RESULTS 3 id1 id2 id3"
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 3
        assert len(result.results) == 3
        assert [r.primary_key for r in result.results] == ["id1", "id2", "id3"]
        assert all(r.snippet is None for r in result.results)

    def test_highlight_with_debug_block(self):
        response = (
            "OK RESULTS 1\n"
            "id1\tmatched <em>x</em>\n"
            "# DEBUG\n"
            "query_time: 1.5\n"
            "terms: 2"
        )
        result = MygramClient._parse_search_response(response)

        assert result.total_count == 1
        assert result.results[0].primary_key == "id1"
        assert result.results[0].snippet == "matched <em>x</em>"
        assert result.debug is not None
        assert result.debug.query_time_ms == 1.5


class TestFacetResponseParsing:
    """Tests for parsing FACET responses."""

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
        response = "OK FACET 0"
        result = MygramClient._parse_facet_response(response)

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
        response = "OK FACET 1\nx\t5\n"
        result = MygramClient._parse_facet_response(response)

        assert len(result.results) == 1
        assert result.results[0] == FacetValue(value="x", count=5)

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
        response = "OK FACET 1\nno_tab_here"
        with pytest.raises(ProtocolError, match="Invalid FACET row"):
            MygramClient._parse_facet_response(response)

    def test_row_with_non_numeric_count_rejected(self):
        response = "OK FACET 1\na\tnotanumber"
        with pytest.raises(ProtocolError, match="Invalid FACET count for a"):
            MygramClient._parse_facet_response(response)

    def test_value_with_spaces_preserved(self):
        """Facet values may contain arbitrary characters (including spaces)."""
        response = "OK FACET 1\nhello world\t5"
        result = MygramClient._parse_facet_response(response)

        assert result.results[0].value == "hello world"
        assert result.results[0].count == 5


# ---------------------------------------------------------------------------
# Response completion detection
# ---------------------------------------------------------------------------


class TestResponseCompletionV16:
    """Tests for v1.6 response completion detection."""

    def _make_client(self):
        return MygramClient()

    def test_facet_response_incomplete(self):
        client = self._make_client()
        buffer = "OK FACET 2\nvalue1\t5"
        assert not client._is_response_complete(buffer)

    def test_facet_response_complete_lf(self):
        client = self._make_client()
        buffer = "OK FACET 2\nvalue1\t5\nvalue2\t3\n\n"
        assert client._is_response_complete(buffer)

    def test_facet_response_complete_crlf(self):
        client = self._make_client()
        buffer = "OK FACET 2\r\nvalue1\t5\r\nvalue2\t3\r\n\r\n"
        assert client._is_response_complete(buffer)

    def test_facet_empty_complete(self):
        client = self._make_client()
        buffer = "OK FACET 0\n\n"
        assert client._is_response_complete(buffer)

    def test_highlight_response_incomplete(self):
        client = self._make_client()
        buffer = "OK RESULTS 2\nid1\tsnippet1"
        assert not client._is_response_complete(buffer)

    def test_highlight_response_complete(self):
        client = self._make_client()
        buffer = "OK RESULTS 2\nid1\tsnippet1\nid2\tsnippet2\n\n"
        assert client._is_response_complete(buffer)

    def test_classic_search_response_still_complete(self):
        """Regression: single-line SEARCH response should still terminate on \\n."""
        client = self._make_client()
        buffer = "OK RESULTS 2 id1 id2\n"
        assert client._is_response_complete(buffer)
