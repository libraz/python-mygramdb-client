"""Tests for search expression parser."""
import pytest

from mygramdb_client.search_expression import (
    convert_search_expression,
    has_complex_expression,
    parse_search_expression,
    simplify_search_expression,
    to_query_string,
)


class TestParseSearchExpression:
    """Tests for parse_search_expression function."""

    def test_empty_expression_raises_error(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_search_expression("")

    def test_whitespace_only_raises_error(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_search_expression("   ")

    def test_single_word(self):
        result = parse_search_expression("golang")
        assert result.optional_terms == ["golang"]
        assert result.required_terms == []
        assert result.excluded_terms == []

    def test_multiple_words(self):
        result = parse_search_expression("golang tutorial")
        assert result.optional_terms == ["golang", "tutorial"]

    def test_required_term_with_plus(self):
        result = parse_search_expression("+golang")
        assert result.required_terms == ["golang"]
        assert result.optional_terms == []

    def test_excluded_term_with_minus(self):
        result = parse_search_expression("-deprecated")
        assert result.excluded_terms == ["deprecated"]

    def test_mixed_terms(self):
        result = parse_search_expression("+golang tutorial -deprecated")
        assert result.required_terms == ["golang"]
        assert result.optional_terms == ["tutorial"]
        assert result.excluded_terms == ["deprecated"]

    def test_quoted_phrase(self):
        result = parse_search_expression('"machine learning"')
        assert result.optional_terms == ['"machine learning"']

    def test_required_quoted_phrase(self):
        result = parse_search_expression('+"machine learning"')
        assert result.required_terms == ['"machine learning"']

    def test_excluded_quoted_phrase(self):
        result = parse_search_expression('-"old version"')
        assert result.excluded_terms == ['"old version"']

    def test_unterminated_quote_raises_error(self):
        with pytest.raises(ValueError, match="Unterminated quoted string"):
            parse_search_expression('"unterminated')

    def test_plus_without_term_raises_error(self):
        with pytest.raises(ValueError, match="Expected term after"):
            parse_search_expression("+")

    def test_minus_without_term_raises_error(self):
        with pytest.raises(ValueError, match="Expected term after"):
            parse_search_expression("-")

    def test_or_operator_marks_complex(self):
        result = parse_search_expression("python OR ruby")
        assert result.raw_expression == "python OR ruby"

    def test_parentheses_marks_complex(self):
        result = parse_search_expression("(golang tutorial)")
        assert result.raw_expression == "(golang tutorial)"

    def test_fullwidth_space_normalization(self):
        # Full-width space U+3000
        result = parse_search_expression("golang\u3000tutorial")
        assert result.optional_terms == ["golang", "tutorial"]


class TestHasComplexExpression:
    """Tests for has_complex_expression function."""

    def test_simple_expression_is_not_complex(self):
        expr = parse_search_expression("golang tutorial")
        assert has_complex_expression(expr) is False

    def test_or_expression_is_complex(self):
        expr = parse_search_expression("python OR ruby")
        assert has_complex_expression(expr) is True

    def test_parentheses_expression_is_complex(self):
        expr = parse_search_expression("(golang tutorial)")
        assert has_complex_expression(expr) is True


class TestToQueryString:
    """Tests for to_query_string function."""

    def test_optional_terms_joined_with_or(self):
        expr = parse_search_expression("python ruby")
        result = to_query_string(expr)
        assert result == "python OR ruby"

    def test_required_terms_joined_with_and(self):
        expr = parse_search_expression("+golang +tutorial")
        result = to_query_string(expr)
        assert result == "golang AND tutorial"

    def test_excluded_terms_prefixed_with_not(self):
        expr = parse_search_expression("-deprecated -old")
        result = to_query_string(expr)
        assert result == "NOT deprecated AND NOT old"

    def test_mixed_terms(self):
        expr = parse_search_expression("+golang tutorial -deprecated")
        result = to_query_string(expr)
        # Required first, then optional (as AND since required exists), then NOT
        assert "golang" in result
        assert "tutorial" in result
        assert "NOT deprecated" in result


class TestConvertSearchExpression:
    """Tests for convert_search_expression function."""

    def test_simple_conversion(self):
        result = convert_search_expression("+golang tutorial")
        assert "golang" in result
        assert "tutorial" in result

    def test_complex_expression_returns_raw(self):
        result = convert_search_expression("python OR ruby")
        assert result == "python OR ruby"


class TestSimplifySearchExpression:
    """Tests for simplify_search_expression function."""

    def test_basic_simplification(self):
        result = simplify_search_expression("+golang tutorial -deprecated")
        assert result.main_term == "golang"
        assert result.and_terms == ["tutorial"]
        assert result.not_terms == ["deprecated"]

    def test_optional_terms_only(self):
        result = simplify_search_expression("python ruby")
        assert result.main_term == "python"
        assert result.and_terms == ["ruby"]
        assert result.not_terms == []

    def test_no_positive_terms_raises_error(self):
        with pytest.raises(ValueError, match="at least one positive term"):
            simplify_search_expression("-deprecated -old")
