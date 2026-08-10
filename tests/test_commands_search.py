"""Command construction for the query surface: SEARCH, COUNT and search_raw.

Every test here asserts on what the client puts on the wire — clause presence,
clause order, quoting and the identity passed through. Response parsing lives
in ``test_client.py``; FACET has its own file.
"""
import asyncio

import pytest

from mygramdb_client import (
    ClientConfig,
    CountOptions,
    FilterCondition,
    FilterOp,
    HighlightOptions,
    MygramClient,
    QueryMode,
    SearchOptions,
    SearchRawOptions,
)
from mygramdb_client.errors import InputValidationError

from .command_capture import capture_command, run_capturing, unreachable_client


async def build_search_command(table: str, query: str, opts: SearchOptions) -> str:
    return await capture_command(lambda client: client.search(table, query, opts))


# ---------------------------------------------------------------------------
# Table identity and term quoting
# ---------------------------------------------------------------------------


class TestTableIdentityPassThrough:
    """A database-qualified identity reaches the server unchanged (v1.7+)."""

    def test_search_passes_qualified_identity(self):
        commands, _ = run_capturing(
            lambda c: c.search("app_db.articles", "hello")
        )
        assert "SEARCH app_db.articles hello" in commands[0]

    def test_count_get_facet_pass_qualified_identity(self):
        def respond(command):
            if command.startswith("COUNT"):
                return "OK COUNT 0"
            if command.startswith("GET"):
                return "OK DOC pk1"
            return "OK FACET 0"

        commands, _ = run_capturing(
            lambda c: c.count("app_db.articles", "x"), response=respond
        )
        assert "COUNT app_db.articles x" in commands[0]

        commands, _ = run_capturing(
            lambda c: c.get("app_db.articles", "pk1"), response=respond
        )
        assert "GET app_db.articles pk1" in commands[0]

        commands, _ = run_capturing(
            lambda c: c.facet("app_db.articles", "category"), response=respond
        )
        assert "FACET app_db.articles category" in commands[0]


class TestTermQuoting:
    def test_quotes_multiword_and_not_filter(self):
        commands, _ = run_capturing(
            lambda c: c.search(
                "articles", "hello",
                SearchOptions(
                    and_terms=["machine learning"],
                    not_terms=["old stuff"],
                    filters={"status": "in review"},
                ),
            )
        )
        cmd = commands[0]
        assert 'AND "machine learning"' in cmd
        assert 'NOT "old stuff"' in cmd
        assert 'FILTER status = "in review"' in cmd


# ---------------------------------------------------------------------------
# FILTER clauses
# ---------------------------------------------------------------------------


class TestComparisonFilters:
    """FILTER clauses carrying an operator other than ``=`` (v1.9+)."""

    async def test_search_emits_operator_filters(self):
        cmd = await build_search_command(
            "articles",
            "python",
            SearchOptions(
                limit=5,
                filter_conditions=[
                    FilterCondition("views", "100", FilterOp.GTE),
                    FilterCondition("status", "draft", FilterOp.NE),
                ],
            ),
        )
        assert cmd == (
            "SEARCH articles python FILTER views >= 100 "
            "FILTER status != draft LIMIT 5"
        )

    async def test_equality_filters_precede_comparison_filters(self):
        cmd = await build_search_command(
            "articles",
            "python",
            SearchOptions(
                limit=5,
                filters={"lang": "ja"},
                filter_conditions=[FilterCondition("views", "100", FilterOp.LT)],
            ),
        )
        assert cmd == (
            "SEARCH articles python FILTER lang = ja "
            "FILTER views < 100 LIMIT 5"
        )

    async def test_count_emits_operator_filters(self):
        cmd = await capture_command(
            lambda client: client.count(
                "articles",
                "python",
                CountOptions(
                    filter_conditions=[FilterCondition("views", "100", FilterOp.GT)]
                ),
            )
        )
        assert cmd == "COUNT articles python FILTER views > 100"

    async def test_value_with_whitespace_is_quoted(self):
        cmd = await build_search_command(
            "articles",
            "python",
            SearchOptions(
                limit=5,
                filter_conditions=[FilterCondition("author", "Ada Lovelace")],
            ),
        )
        assert '"Ada Lovelace"' in cmd

    async def test_column_with_whitespace_is_rejected(self):
        client = MygramClient(ClientConfig())
        with pytest.raises(InputValidationError, match="whitespace"):
            await client.search(
                "articles",
                "python",
                SearchOptions(
                    filter_conditions=[FilterCondition("bad column", "1")]
                ),
            )

    async def test_control_character_in_value_is_rejected(self):
        client = MygramClient(ClientConfig())
        with pytest.raises(InputValidationError, match="control characters"):
            await client.search(
                "articles",
                "python",
                SearchOptions(
                    filter_conditions=[FilterCondition("views", "1\n2")]
                ),
            )

    async def test_unknown_operator_is_rejected(self):
        client = MygramClient(ClientConfig())
        with pytest.raises(InputValidationError, match="invalid operator"):
            await client.search(
                "articles",
                "python",
                SearchOptions(
                    filter_conditions=[
                        FilterCondition("views", "1", "LIKE"),  # type: ignore[arg-type]
                    ]
                ),
            )


# ---------------------------------------------------------------------------
# SORT / FUZZY / HIGHLIGHT clauses
# ---------------------------------------------------------------------------


class TestSortClause:
    """SORT emission, including BM25 relevance via the ``_score`` column."""

    async def test_score_sort_desc(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(sort_column="_score", sort_desc=True),
        )
        assert "SORT _score DESC" in cmd

    async def test_score_sort_asc(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(sort_column="_score", sort_desc=False),
        )
        assert "SORT _score ASC" in cmd

    async def test_ascending_without_a_column_uses_the_shorthand(self):
        # Without a column the server orders by primary key descending, so an
        # ascending request must still emit a clause or it is silently lost.
        cmd = await build_search_command(
            "articles", "hello", SearchOptions(sort_desc=False),
        )
        assert "SORT ASC" in cmd

    async def test_descending_without_a_column_omits_the_clause(self):
        cmd = await build_search_command(
            "articles", "hello", SearchOptions(sort_desc=True),
        )
        assert "SORT" not in cmd


class TestFuzzyClause:
    async def test_fuzzy_zero_omits_clause(self):
        cmd = await build_search_command("articles", "hello", SearchOptions(fuzzy=0))
        assert "FUZZY" not in cmd

    async def test_fuzzy_one(self):
        cmd = await build_search_command("articles", "hello", SearchOptions(fuzzy=1))
        assert "FUZZY 1" in cmd

    async def test_fuzzy_two(self):
        cmd = await build_search_command("articles", "hello", SearchOptions(fuzzy=2))
        assert "FUZZY 2" in cmd

    async def test_fuzzy_appears_after_sort(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(fuzzy=1, sort_column="id"),
        )
        assert cmd.index("SORT") < cmd.index("FUZZY")


class TestHighlightClause:
    async def test_highlight_default(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions()),
        )
        assert "HIGHLIGHT" in cmd
        assert "TAG" not in cmd
        assert "SNIPPET_LEN" not in cmd
        assert "MAX_FRAGMENTS" not in cmd

    async def test_highlight_with_custom_tags(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(
                open_tag="<b>", close_tag="</b>",
            )),
        )
        assert "HIGHLIGHT TAG <b> </b>" in cmd

    async def test_highlight_with_snippet_len(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(snippet_len=200)),
        )
        assert "SNIPPET_LEN 200" in cmd

    async def test_highlight_with_max_fragments(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(max_fragments=5)),
        )
        assert "MAX_FRAGMENTS 5" in cmd

    async def test_highlight_full_options(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions(
                open_tag="<mark>",
                close_tag="</mark>",
                snippet_len=150,
                max_fragments=3,
            )),
        )
        assert "HIGHLIGHT TAG <mark> </mark> SNIPPET_LEN 150 MAX_FRAGMENTS 3" in cmd

    async def test_highlight_appears_after_fuzzy(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(fuzzy=1, highlight=HighlightOptions()),
        )
        assert cmd.index("FUZZY") < cmd.index("HIGHLIGHT")

    async def test_highlight_before_limit(self):
        cmd = await build_search_command(
            "articles", "hello",
            SearchOptions(highlight=HighlightOptions()),
        )
        assert cmd.index("HIGHLIGHT") < cmd.index("LIMIT")

    def test_search_with_highlights_enables_the_clause(self):
        commands, result = run_capturing(
            lambda c: c.search_with_highlights("articles", "hello"),
            response="OK RESULTS 1\npk1\t<em>hello</em>\n",
        )
        assert "HIGHLIGHT" in commands[0]
        assert result.results[0].primary_key == "pk1"
        assert result.results[0].snippet == "<em>hello</em>"


# ---------------------------------------------------------------------------
# Query modes: literal, boolean, and the pre-built search_raw expression
# ---------------------------------------------------------------------------


class TestBooleanQueryMode:
    """``QueryMode.BOOLEAN`` on the typed search surface (v1.10+)."""

    async def test_boolean_mode_sends_the_expression_verbatim(self):
        cmd = await build_search_command(
            "articles",
            "alpha AND (beta OR gamma)",
            SearchOptions(limit=5, query_mode=QueryMode.BOOLEAN),
        )
        assert cmd == "SEARCH articles alpha AND (beta OR gamma) LIMIT 5"

    async def test_boolean_mode_combines_with_typed_options(self):
        # This is the capability search_raw cannot express: an expression plus
        # filters, sorting, fuzzy matching and highlighting in one command.
        cmd = await build_search_command(
            "articles",
            "alpha OR beta",
            SearchOptions(
                limit=5,
                query_mode=QueryMode.BOOLEAN,
                filters={"lang": "ja"},
                sort_column="views",
                fuzzy=1,
            ),
        )
        assert cmd == (
            "SEARCH articles alpha OR beta FILTER lang = ja "
            "SORT views DESC FUZZY 1 LIMIT 5"
        )

    async def test_literal_mode_remains_the_default(self):
        cmd = await capture_command(
            lambda client: client.search("articles", "alpha AND beta")
        )
        assert '"alpha AND beta"' in cmd

    async def test_boolean_mode_rejects_an_empty_expression(self):
        client = MygramClient(ClientConfig())
        with pytest.raises(InputValidationError, match="must not be empty"):
            await client.search(
                "articles", "", SearchOptions(query_mode=QueryMode.BOOLEAN)
            )

    async def test_unknown_query_mode_is_rejected(self):
        client = MygramClient(ClientConfig())
        with pytest.raises(InputValidationError, match="Invalid query_mode"):
            await client.search(
                "articles",
                "alpha",
                SearchOptions(query_mode="fuzzy-ish"),  # type: ignore[arg-type]
            )


class TestSearchRaw:
    """A pre-built expression is sent unquoted so the server parses it (v1.8+)."""

    def test_sends_boolean_expression_verbatim(self):
        commands, _ = run_capturing(
            lambda c: c.search_raw(
                "articles", "python OR (ruby AND rails)", SearchRawOptions(limit=50)
            )
        )
        cmd = commands[0]
        assert "SEARCH articles python OR (ruby AND rails)" in cmd
        assert '"python OR (ruby AND rails)"' not in cmd
        assert cmd.rstrip().endswith("LIMIT 50")

    async def test_grouped_expression_reaches_the_server_verbatim(self):
        cmd = await capture_command(
            lambda client: client.search_raw(
                "articles",
                "(ruby OR python) AND machine",
                SearchRawOptions(limit=5),
            )
        )
        assert cmd == "SEARCH articles (ruby OR python) AND machine LIMIT 5"

    async def test_plain_search_still_quotes_its_query(self):
        # search() keeps auto-quoting literal text; only search_raw is verbatim.
        cmd = await capture_command(
            lambda client: client.search("articles", "hello world")
        )
        assert '"hello world"' in cmd

    def test_emits_bare_offset_when_only_offset_set(self):
        commands, _ = run_capturing(
            lambda c: c.search_raw("articles", "a OR b", SearchRawOptions(offset=20))
        )
        assert commands[0].rstrip().endswith("OFFSET 20")

    def test_rejects_empty_raw_query(self):
        async def issue():
            await unreachable_client().search_raw("articles", "")

        with pytest.raises(InputValidationError):
            asyncio.run(issue())

    def test_with_highlights_appends_clause_and_parses_snippet(self):
        commands, result = run_capturing(
            lambda c: c.search_raw_with_highlights("articles", "a OR b"),
            response="OK RESULTS 1\npk1\tthe <em>a</em> snippet\n",
        )
        assert "HIGHLIGHT" in commands[0]
        assert result.results[0].primary_key == "pk1"
        assert result.results[0].snippet == "the <em>a</em> snippet"
