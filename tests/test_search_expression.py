"""
Tests for the web-style search expression parser.

Mirrors mygram-db's tests/client/search_expression_test.cpp: unprefixed
terms are required (implicit AND), a parenthesized group after +/- stays one
required/excluded entry, and a literal term colliding with a clause keyword
is quoted through the shared wire-quoting decision.
"""
import pytest

from mygramdb_client.search_expression import (
    convert_search_expression,
    has_complex_expression,
    parse_search_expression,
    simplify_search_expression,
    to_query_string,
)


class TestParseSearchExpression:
    """Tests for parse_search_expression."""

    def test_empty_expression_raises_error(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_search_expression("")

    def test_whitespace_only_raises_error(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_search_expression("   ")

    def test_single_word_is_required(self):
        result = parse_search_expression("golang")
        assert result.required_terms == ["golang"]
        assert result.excluded_terms == []
        assert not hasattr(result, "optional_terms")

    def test_multiple_words_are_implicit_and(self):
        result = parse_search_expression("golang tutorial")
        assert result.required_terms == ["golang", "tutorial"]

    def test_required_term_with_plus(self):
        result = parse_search_expression("+golang")
        assert result.required_terms == ["golang"]

    def test_excluded_term_with_minus(self):
        result = parse_search_expression("-old")
        assert result.required_terms == []
        assert result.excluded_terms == ["old"]

    def test_multiple_required_terms(self):
        result = parse_search_expression("+golang +tutorial +2024")
        assert result.required_terms == ["golang", "tutorial", "2024"]

    def test_required_and_excluded(self):
        result = parse_search_expression("+golang -old")
        assert result.required_terms == ["golang"]
        assert result.excluded_terms == ["old"]

    def test_or_expression_is_complex(self):
        result = parse_search_expression("python OR ruby")
        assert has_complex_expression(result)
        assert result.raw_expression != ""
        assert result.required_terms == []
        assert result.excluded_terms == []

    @pytest.mark.parametrize("term", ["ORANGE", "ORDER", "FLOOR", "orchestra"])
    def test_or_substring_inside_ordinary_word_is_not_complex(self, term):
        result = parse_search_expression(term)
        assert not has_complex_expression(result)
        assert result.required_terms == [term]

    def test_parenthesized_expression_is_complex(self):
        result = parse_search_expression("(tutorial OR guide)")
        assert has_complex_expression(result)
        assert result.raw_expression != ""

    def test_required_with_parenthesized_or(self):
        result = parse_search_expression("+golang +(tutorial OR guide)")
        assert result.required_terms[0] == "golang"
        assert has_complex_expression(result)

    def test_complex_expression(self):
        result = parse_search_expression(
            "+golang +(tutorial OR guide) -old -deprecated"
        )
        assert result.required_terms[0] == "golang"
        assert result.excluded_terms == ["old", "deprecated"]
        assert has_complex_expression(result)

    def test_whitespace_handling(self):
        result = parse_search_expression("  +golang   -old   tutorial  ")
        assert result.required_terms == ["golang", "tutorial"]
        assert result.excluded_terms == ["old"]

    def test_japanese_terms(self):
        result = parse_search_expression("+日本語 -古い チュートリアル")
        assert result.required_terms == ["日本語", "チュートリアル"]
        assert result.excluded_terms == ["古い"]

    def test_quoted_phrase_stored_as_plain_text(self):
        result = parse_search_expression('"machine learning" tutorial')
        assert result.required_terms == ["machine learning", "tutorial"]
        assert to_query_string(result) == '"machine learning" AND tutorial'

    def test_quoted_phrase_with_exclusion(self):
        result = parse_search_expression('"deep learning" -tensorflow')
        assert result.required_terms == ["deep learning"]
        assert result.excluded_terms == ["tensorflow"]
        assert to_query_string(result) == '"deep learning" AND NOT tensorflow'

    def test_quoted_phrase_with_or(self):
        result = parse_search_expression('"machine learning" OR "deep learning"')
        assert has_complex_expression(result)
        assert '"machine learning"' in result.raw_expression
        assert '"deep learning"' in result.raw_expression

    def test_fullwidth_space_delimiter(self):
        result = parse_search_expression("golang　tutorial")
        assert result.required_terms == ["golang", "tutorial"]

    def test_mixed_ascii_and_fullwidth_spaces(self):
        result = parse_search_expression("golang tutorial　日本語")
        assert result.required_terms == ["golang", "tutorial", "日本語"]

    def test_nbsp_is_a_separator(self):
        # U+00A0 (no-break space): a token boundary just like an ASCII space.
        result = parse_search_expression("golang tutorial")
        assert result.required_terms == ["golang", "tutorial"]

    def test_unterminated_quote_raises_error(self):
        with pytest.raises(ValueError, match="Unterminated quoted string"):
            parse_search_expression('"unterminated')

    def test_plus_without_term_raises_error(self):
        with pytest.raises(ValueError, match="Expected term after"):
            parse_search_expression("+")

    def test_minus_without_term_raises_error(self):
        with pytest.raises(ValueError, match="Expected term after"):
            parse_search_expression("-")

    def test_unbalanced_parens_raises_error(self):
        with pytest.raises(ValueError, match="Unbalanced"):
            parse_search_expression("(golang tutorial")

    @pytest.mark.parametrize("term", ["COVID-19", "e-mail", "UTF-8", "C++"])
    def test_plus_and_minus_inside_terms_are_literal_text(self, term):
        result = parse_search_expression(term)
        assert result.required_terms == [term]
        assert result.excluded_terms == []
        assert convert_search_expression(term) == term

    def test_leading_plus_and_minus_remain_unary_operators(self):
        result = parse_search_expression("+COVID-19 -e-mail C++")
        assert result.required_terms == ["COVID-19", "C++"]
        assert result.excluded_terms == ["e-mail"]

    @pytest.mark.parametrize(
        "expression", ["a OR -b", "a b OR", "foo OR"]
    )
    def test_malformed_or_chains_are_rejected(self, expression):
        with pytest.raises(ValueError):
            convert_search_expression(expression)

    @pytest.mark.parametrize(
        "expression",
        ["a OR (b c", "a OR (b OR", "(a OR", 'a OR "unterminated'],
    )
    def test_errors_inside_or_capture_propagate(self, expression):
        # An error raised while capturing an OR chain (unbalanced parens
        # after OR, an unterminated quote reached from inside OR) must
        # surface as ValueError from the top-level call, not be swallowed.
        with pytest.raises(ValueError):
            convert_search_expression(expression)

    @pytest.mark.parametrize("term", ["OR", "or", "Or", "oR"])
    def test_or_is_recognized_case_insensitively_as_a_whole_word(self, term):
        result = parse_search_expression(f"python {term} ruby")
        assert has_complex_expression(result)
        assert result.raw_expression == "python OR ruby"

    def test_apostrophe_inside_term_is_literal(self):
        result = parse_search_expression("don't stop")
        assert result.required_terms == ["don't", "stop"]
        assert convert_search_expression("don't stop") == '"don\'t" AND stop'


class TestHasComplexExpression:
    """Tests for has_complex_expression."""

    def test_simple_expression_is_not_complex(self):
        assert not has_complex_expression(parse_search_expression("golang tutorial"))

    def test_or_expression_is_complex(self):
        assert has_complex_expression(parse_search_expression("python OR ruby"))

    def test_parentheses_expression_is_complex(self):
        assert has_complex_expression(parse_search_expression("(golang tutorial)"))


class TestToQueryString:
    """Tests for to_query_string."""

    def test_required_terms_joined_with_and(self):
        result = to_query_string(parse_search_expression("+golang +tutorial"))
        assert result == "golang AND tutorial"

    def test_excluded_terms_prefixed_with_not(self):
        result = to_query_string(parse_search_expression("+golang -old"))
        assert result == "golang AND NOT old"

    def test_unprefixed_terms_are_implicit_and(self):
        result = to_query_string(parse_search_expression("python ruby"))
        assert result == "python AND ruby"

    def test_wraps_or_subexpression_in_parens(self):
        result = convert_search_expression("python OR ruby")
        assert result == "(python OR ruby)"

    def test_parenthesized_implicit_and_preserves_whitespace(self):
        assert convert_search_expression("+(machine learning)") == "(machine learning)"
        assert (
            convert_search_expression('+(a "quoted phrase" b)')
            == '(a "quoted phrase" b)'
        )


class TestConvertSearchExpression:
    """Tests for convert_search_expression."""

    def test_simple_conversion(self):
        result = convert_search_expression("+golang -old")
        assert "golang" in result
        assert "NOT old" in result

    def test_quotes_literal_terms_colliding_with_keywords(self):
        assert convert_search_expression("golang not") == 'golang AND "not"'
        assert convert_search_expression("filter") == '"filter"'
        assert convert_search_expression("sort") == '"sort"'
        assert convert_search_expression("NOT") == '"NOT"'
        assert convert_search_expression("golang NOT old") == 'golang AND "NOT" AND old'
        assert convert_search_expression("+not") == '"not"'

    def test_emoji_expression(self):
        result = convert_search_expression("\U0001f600 tutorial -\U0001f389")
        assert "\U0001f600" in result
        assert "tutorial" in result
        assert "NOT \U0001f389" in result


class TestSimplifySearchExpression:
    """Tests for simplify_search_expression."""

    def test_basic_simplification(self):
        result = simplify_search_expression("golang tutorial -old")
        assert result.main_term == "golang"
        assert result.and_terms == ["tutorial"]
        assert result.not_terms == ["old"]

    def test_no_positive_terms_raises_error(self):
        with pytest.raises(ValueError, match="at least one positive term"):
            simplify_search_expression("-old")

    def test_or_only_expression_is_rejected(self):
        # The legacy structured API has no way to represent boolean OR:
        # every consumer of main_term re-applies wire quoting to it, which
        # would wrap "python OR ruby" as one opaque literal-phrase term
        # instead of parsing it as boolean OR.
        with pytest.raises(ValueError):
            simplify_search_expression("python OR ruby")

    def test_parenthesized_or_expression_is_rejected(self):
        with pytest.raises(ValueError):
            simplify_search_expression("(python OR ruby)")

    def test_required_with_or_subexpression_is_rejected(self):
        with pytest.raises(ValueError):
            simplify_search_expression("+golang (tutorial OR guide)")


class TestTopLevelOr:
    """An expression with a top-level OR is one group (implicit AND binds tighter)."""

    @pytest.mark.parametrize(
        "expression, expected",
        [
            ("a OR b c", "(a OR b c)"),
            ("(a OR b c)", "((a OR b c))"),
            ("a OR b c OR d", "(a OR b c OR d)"),
            ("x a OR b", "(x a OR b)"),
            ("a OR (b c) d", "(a OR (b c) d)"),
        ],
    )
    def test_bare_or_expression_matches_its_parenthesized_form(
        self, expression, expected
    ):
        assert convert_search_expression(expression) == expected

    @pytest.mark.parametrize("expression", ["a OR b c", "a OR b c OR d", "x a OR b"])
    def test_wrapped_form_carries_the_same_single_group(self, expression):
        bare = parse_search_expression(expression)
        wrapped = parse_search_expression(f"({expression})")
        assert bare.required_terms == []
        assert wrapped.raw_expression == f"({bare.raw_expression})"

    @pytest.mark.parametrize("expression", ["OR a", "a OR OR b", "+ OR a", "a OR - b"])
    def test_misplaced_or_is_rejected(self, expression):
        with pytest.raises(ValueError):
            convert_search_expression(expression)


class TestGroupFlags:
    """Prefixed groups are tagged structurally, never by their text shape."""

    def test_quoted_phrase_shaped_like_a_group_stays_literal(self):
        assert convert_search_expression('"(a OR b)"') == '"(a OR b)"'
        parsed = parse_search_expression('"(beta)"')
        assert not has_complex_expression(parsed)
        assert simplify_search_expression('"(beta)"').main_term == "(beta)"
        assert simplify_search_expression('foo -"(x)"').not_terms == ["(x)"]

    def test_prefixed_group_is_tagged_structurally(self):
        parsed = parse_search_expression("+golang +(tutorial OR guide) -(old)")
        assert parsed.required_is_group == [False, True]
        assert parsed.excluded_is_group == [True]
        assert (
            to_query_string(parsed)
            == "golang AND (tutorial OR guide) AND NOT (old)"
        )

    def test_flags_run_parallel_to_term_lists(self):
        parsed = parse_search_expression("a +b -c d")
        assert parsed.required_terms == ["a", "b", "d"]
        assert parsed.required_is_group == [False, False, False]
        assert parsed.excluded_is_group == [False]


class TestNegatedGroupInsideGroup:
    """A minus negates only the next operand, and a nested group counts as one."""

    def test_negated_nested_group_excludes_the_whole_group(self):
        assert convert_search_expression("(a -(b c))") == "((a NOT (b c)))"

    def test_dangling_minus_does_not_leak(self):
        assert convert_search_expression("(a -) b") == "b AND ((a))"
        assert convert_search_expression("(a - OR b)") == "((a OR b))"


class TestOrOperatorBoundaries:
    """OR is an operator only as a whole token."""

    @pytest.mark.parametrize("term", ["OR-tools", "OR.", "or's", "OR回路"])
    def test_term_beginning_with_or_is_not_the_operator(self, term):
        parsed = parse_search_expression(term)
        assert not has_complex_expression(parsed)
        assert parsed.required_terms == [term]

    def test_or_prefixed_terms_in_context(self):
        assert convert_search_expression("python OR-tools") == "python AND OR-tools"
        assert convert_search_expression("OR回路 入門") == "OR回路 AND 入門"

    def test_fullwidth_space_delimits_the_operator(self):
        assert convert_search_expression("python　OR　ruby") == "(python OR ruby)"

    def test_operator_next_to_parentheses_and_quotes(self):
        assert convert_search_expression("(a)OR(b)") == "((a) OR (b))"
        assert convert_search_expression('"a"OR"b"') == "(a OR b)"

    def test_or_after_a_prefix_is_a_plain_term(self):
        assert parse_search_expression("+OR").required_terms == ["OR"]
