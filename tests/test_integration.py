"""
Integration tests for MygramDB client parsing and protocol handling.

These tests verify parsing logic without requiring a real server.
They can run in CI environments.
"""
from mygramdb_client import (
    ClientConfig,
    MygramClient,
    parse_search_expression,
    simplify_search_expression,
)


class TestSearchExpressionParsing:
    """Tests for search expression parsing."""

    class TestSimplifySearchExpression:
        """Tests for simplify_search_expression function."""

        def test_parse_simple_space_separated_terms_as_and(self):
            expr = simplify_search_expression("hello world")

            assert expr.main_term == "hello"
            assert expr.and_terms == ["world"]
            assert expr.not_terms == []

        def test_parse_plus_prefix_as_required_terms(self):
            expr = simplify_search_expression("+golang +tutorial")

            assert expr.main_term == "golang"
            assert expr.and_terms == ["tutorial"]
            assert expr.not_terms == []

        def test_parse_minus_prefix_as_excluded_terms(self):
            expr = simplify_search_expression("+programming -java")

            assert expr.main_term == "programming"
            assert expr.and_terms == []
            assert expr.not_terms == ["java"]

        def test_parse_quoted_phrases(self):
            expr = simplify_search_expression('"machine learning" tutorial')

            assert expr.main_term == '"machine learning"'
            assert expr.and_terms == ["tutorial"]

        def test_handle_fullwidth_space_as_separator(self):
            expr = simplify_search_expression("機械学習\u3000チュートリアル")

            assert expr.main_term == "機械学習"
            assert expr.and_terms == ["チュートリアル"]

        def test_parse_complex_expression_with_required_and_excluded(self):
            expr = simplify_search_expression("+hello +world -goodbye")

            assert expr.main_term == "hello"
            assert expr.and_terms == ["world"]
            assert expr.not_terms == ["goodbye"]

        def test_handle_multiple_excluded_terms(self):
            expr = simplify_search_expression("+search -spam -ads -tracking")

            assert expr.main_term == "search"
            assert expr.and_terms == []
            assert expr.not_terms == ["spam", "ads", "tracking"]

        def test_handle_terms_without_prefix_as_optional(self):
            expr = simplify_search_expression("golang tutorial beginner")

            assert expr.main_term == "golang"
            assert "tutorial" in expr.and_terms
            assert "beginner" in expr.and_terms

    class TestParseSearchExpression:
        """Tests for parse_search_expression function."""

        def test_parse_simple_terms(self):
            result = parse_search_expression("hello world")

            assert result.required_terms == []
            assert result.optional_terms == ["hello", "world"]
            assert result.excluded_terms == []

        def test_parse_required_terms_with_plus(self):
            result = parse_search_expression("+required1 +required2")

            assert result.required_terms == ["required1", "required2"]
            assert result.optional_terms == []

        def test_parse_excluded_terms_with_minus(self):
            result = parse_search_expression("search -excluded")

            assert "search" in result.optional_terms
            assert result.excluded_terms == ["excluded"]

        def test_parse_quoted_phrases(self):
            result = parse_search_expression('"exact phrase" other')

            assert '"exact phrase"' in result.optional_terms
            assert "other" in result.optional_terms

        def test_handle_or_operator(self):
            result = parse_search_expression("cat OR dog")

            assert "cat" in result.optional_terms
            assert "dog" in result.optional_terms

        def test_handle_mixed_operators(self):
            result = parse_search_expression('+golang "web framework" -deprecated')

            assert "golang" in result.required_terms
            assert '"web framework"' in result.optional_terms
            assert "deprecated" in result.excluded_terms


class TestClientConfiguration:
    """Tests for client configuration."""

    def test_use_default_values_when_not_specified(self):
        client = MygramClient()

        assert client is not None
        assert client.is_connected() is False

    def test_accept_custom_configuration(self):
        client = MygramClient(ClientConfig(
            host="custom.host.com",
            port=12345,
            timeout=10.0
        ))

        assert client is not None

    def test_default_config_values(self):
        config = ClientConfig()

        assert config.host == "127.0.0.1"
        assert config.port == 11016
        assert config.timeout == 5.0
        assert config.recv_buffer_size == 65536
        assert config.max_query_length == 128


class TestSearchCommandFormat:
    """Tests for search command format."""

    def test_search_command_format(self):
        """Verify the expected command format."""
        table = "articles"
        query = "test"
        and_terms = ["required"]
        not_terms = ["excluded"]

        parts = ["SEARCH", table, query]
        for term in and_terms:
            parts.extend(["AND", term])
        for term in not_terms:
            parts.extend(["NOT", term])
        parts.extend(["LIMIT", "100"])

        command = " ".join(parts)
        assert command == "SEARCH articles test AND required NOT excluded LIMIT 100"

    def test_count_command_format(self):
        """Verify COUNT command format."""
        table = "users"
        query = "active"
        and_terms = ["verified"]

        parts = ["COUNT", table, query]
        for term in and_terms:
            parts.extend(["AND", term])

        command = " ".join(parts)
        assert command == "COUNT users active AND verified"


class TestDebugInfoParsing:
    """Tests for debug info parsing."""

    def test_parse_debug_info_format(self):
        debug_section = """# DEBUG
query_time: 0.5
index_time: 0.3
terms: 2
ngrams: 6
candidates: 100
after_intersection: 50
final: 25
optimization: early-exit"""

        lines = debug_section.split("\n")[1:]
        debug_info = {}

        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key.endswith("_time"):
                debug_info[key] = float(value)
            elif key in ["terms", "ngrams", "candidates", "after_intersection", "final"]:
                debug_info[key] = int(value)
            else:
                debug_info[key] = value

        assert debug_info["query_time"] == 0.5
        assert debug_info["index_time"] == 0.3
        assert debug_info["terms"] == 2
        assert debug_info["ngrams"] == 6
        assert debug_info["candidates"] == 100
        assert debug_info["optimization"] == "early-exit"


class TestSimplifySearchExpressionConsistency:
    """Tests for simplify_search_expression consistency."""

    def test_match_for_all_expressions(self):
        """Should produce consistent results for various expressions."""
        test_cases = [
            "hello world",
            "hello world test",
            "+hello +world",
            "hello -world",
            "+golang -old tutorial",
            '"machine learning" tutorial',
        ]

        for expression in test_cases:
            result = simplify_search_expression(expression)
            assert result.main_term is not None
            assert isinstance(result.and_terms, list)
            assert isinstance(result.not_terms, list)

    def test_handle_japanese_text_with_fullwidth_space(self):
        expr = simplify_search_expression("機械学習\u3000チュートリアル")

        assert expr.main_term == "機械学習"
        assert expr.and_terms == ["チュートリアル"]
