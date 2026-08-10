"""Tests for command validation, quoting and identity utilities.

These are the pure helpers that decide what may be sent and how it is spelled
on the wire; the command builders that consume them are asserted in the
``test_commands_*`` files.
"""
import pytest

from mygramdb_client import HighlightOptions, parse_table_identity, qualify_table_identity
from mygramdb_client.command_utils import (
    MAX_HIGHLIGHT_TAG_BYTES,
    calculate_query_expression_length,
    ensure_query_length_within_limit,
    ensure_safe_command_value,
    ensure_safe_filters,
    ensure_safe_string_array,
    escape_query_string,
    has_control_characters,
    quote_command_argument,
    validate_facet_column,
    validate_fuzzy,
    validate_highlight,
    validate_identifier,
    validate_primary_key,
    validate_table_name,
)
from mygramdb_client.errors import InputValidationError


class TestHasControlCharacters:
    """Tests for has_control_characters function."""

    def test_normal_string_has_no_control_chars(self):
        assert has_control_characters("hello world") is False

    def test_null_character(self):
        assert has_control_characters("hello\x00world") is True

    def test_newline_character(self):
        assert has_control_characters("hello\nworld") is True

    def test_tab_character(self):
        assert has_control_characters("hello\tworld") is True

    def test_carriage_return(self):
        assert has_control_characters("hello\rworld") is True

    def test_delete_character(self):
        assert has_control_characters("hello\x7fworld") is True

    def test_unicode_is_allowed(self):
        assert has_control_characters("こんにちは") is False


class TestEnsureSafeCommandValue:
    """Tests for ensure_safe_command_value function."""

    def test_valid_value_passes(self):
        ensure_safe_command_value("valid value", "field")

    def test_control_char_raises_error(self):
        with pytest.raises(InputValidationError, match="contains invalid control"):
            ensure_safe_command_value("bad\x00value", "field")


class TestEnsureSafeStringArray:
    """Tests for ensure_safe_string_array function."""

    def test_valid_array_passes(self):
        ensure_safe_string_array(["a", "b", "c"], "terms")

    def test_empty_array_passes(self):
        ensure_safe_string_array([], "terms")

    def test_control_char_in_array_raises_error(self):
        with pytest.raises(InputValidationError, match="terms\\[1\\]"):
            ensure_safe_string_array(["good", "bad\nvalue", "ok"], "terms")


class TestEnsureSafeFilters:
    """Tests for ensure_safe_filters function."""

    def test_valid_filters_pass(self):
        ensure_safe_filters({"key": "value", "status": "1"})

    def test_empty_filters_pass(self):
        ensure_safe_filters({})

    def test_control_char_in_key_raises_error(self):
        with pytest.raises(InputValidationError, match="Filter key"):
            ensure_safe_filters({"bad\x00key": "value"})

    def test_control_char_in_value_raises_error(self):
        with pytest.raises(InputValidationError, match="Filter value"):
            ensure_safe_filters({"key": "bad\x00value"})


class TestCalculateQueryExpressionLength:
    """Tests for calculate_query_expression_length function."""

    def test_query_only(self):
        assert calculate_query_expression_length("hello") == 5

    def test_with_and_terms(self):
        assert calculate_query_expression_length("hello", ["world"]) == 10

    def test_with_not_terms(self):
        assert calculate_query_expression_length("hello", None, ["bad"]) == 8

    def test_with_both_terms(self):
        length = calculate_query_expression_length("hello", ["world"], ["bad"])
        assert length == 13


class TestEnsureQueryLengthWithinLimit:
    """Tests for ensure_query_length_within_limit function."""

    def test_within_limit_passes(self):
        ensure_query_length_within_limit("hello", 10)

    def test_exceeds_limit_raises_error(self):
        with pytest.raises(InputValidationError, match="exceeds maximum"):
            ensure_query_length_within_limit("hello world", 5)

    def test_with_terms_within_limit_passes(self):
        ensure_query_length_within_limit("hi", 10, ["hey"], ["no"])

    def test_with_terms_exceeds_limit_raises_error(self):
        with pytest.raises(InputValidationError):
            ensure_query_length_within_limit("hello", 5, ["world"])


class TestValidateTableName:
    """Tests for validate_table_name function."""

    def test_valid_table_name_passes(self):
        validate_table_name("articles")

    def test_empty_table_name_raises_error(self):
        with pytest.raises(InputValidationError, match="cannot be empty"):
            validate_table_name("")

    def test_table_name_with_control_char_raises_error(self):
        with pytest.raises(InputValidationError, match="contains invalid"):
            validate_table_name("bad\x00table")


class TestValidatePrimaryKey:
    """Tests for validate_primary_key function."""

    def test_valid_primary_key_passes(self):
        validate_primary_key("12345")

    def test_empty_primary_key_raises_error(self):
        with pytest.raises(InputValidationError, match="cannot be empty"):
            validate_primary_key("")

    def test_primary_key_with_control_char_raises_error(self):
        with pytest.raises(InputValidationError, match="contains invalid"):
            validate_primary_key("bad\x00key")


class TestNewMethodInputValidation:
    """Tests that new methods reject control characters in inputs."""

    def test_filepath_with_control_char_rejected(self):
        with pytest.raises(InputValidationError, match="contains invalid"):
            ensure_safe_command_value("/path/\x00bad", "filepath")

    def test_filepath_with_newline_rejected(self):
        with pytest.raises(InputValidationError, match="contains invalid"):
            ensure_safe_command_value("/path/\nbad", "filepath")

    def test_filepath_valid_passes(self):
        ensure_safe_command_value("/backup/dump-2024.dmp", "filepath")

    def test_table_for_cache_clear_with_control_char_rejected(self):
        with pytest.raises(InputValidationError, match="contains invalid"):
            ensure_safe_command_value("table\r\nname", "table")

    def test_table_for_optimize_with_control_char_rejected(self):
        with pytest.raises(InputValidationError, match="contains invalid"):
            ensure_safe_command_value("table\x00name", "table")


class TestValidateIdentifier:
    """Tests for validate_identifier."""

    def test_valid_identifier_passes(self):
        validate_identifier("articles", "table name")

    def test_unicode_identifier_passes(self):
        validate_identifier("記事", "table name")

    def test_empty_identifier_rejected(self):
        with pytest.raises(InputValidationError, match="is empty"):
            validate_identifier("", "table name")

    def test_space_rejected(self):
        with pytest.raises(InputValidationError, match="whitespace"):
            validate_identifier("my table", "table name")

    def test_leading_space_rejected(self):
        with pytest.raises(InputValidationError, match="whitespace"):
            validate_identifier(" table", "table name")

    def test_trailing_space_rejected(self):
        with pytest.raises(InputValidationError, match="whitespace"):
            validate_identifier("table ", "table name")

    def test_tab_rejected(self):
        # Tab is a control character (0x09); rejected with control-char error
        with pytest.raises(InputValidationError, match="control character"):
            validate_identifier("a\tb", "table name")

    def test_newline_rejected(self):
        with pytest.raises(InputValidationError, match="control character"):
            validate_identifier("a\nb", "table name")

    def test_carriage_return_rejected(self):
        with pytest.raises(InputValidationError, match="control character"):
            validate_identifier("a\rb", "table name")

    def test_null_byte_rejected(self):
        with pytest.raises(InputValidationError, match="control character"):
            validate_identifier("a\x00b", "table name")

    def test_field_name_appears_in_error(self):
        with pytest.raises(InputValidationError, match="filter key"):
            validate_identifier("a b", "filter key")

    @pytest.mark.parametrize("value", ['a"b', "a'b", "a\\b"])
    def test_protocol_delimiters_rejected(self, value):
        # An identifier is emitted bare, so a quote or backslash would flip the
        # tokenizer's quote/escape state and swallow the rest of the command.
        with pytest.raises(InputValidationError, match="protocol delimiter"):
            validate_identifier(value, "table name")


class TestValidateTableNameWhitespace:
    """validate_table_name should reject whitespace."""

    def test_table_with_space_rejected(self):
        with pytest.raises(InputValidationError, match="whitespace"):
            validate_table_name("my table")

    def test_table_with_tab_rejected(self):
        # Tab is rejected as a control character before the whitespace check
        with pytest.raises(InputValidationError, match="control"):
            validate_table_name("my\ttable")


class TestValidatePrimaryKeyWhitespace:
    """validate_primary_key should reject whitespace."""

    def test_primary_key_with_space_rejected(self):
        with pytest.raises(InputValidationError, match="whitespace"):
            validate_primary_key("pk 1")


class TestEscapeQueryString:
    """Tests for escape_query_string."""

    def test_empty_string_returns_double_quote_pair(self):
        assert escape_query_string("") == '""'

    def test_simple_word_unchanged(self):
        assert escape_query_string("hello") == "hello"

    def test_unicode_unchanged(self):
        assert escape_query_string("こんにちは") == "こんにちは"

    def test_value_with_space_quoted(self):
        assert escape_query_string("hello world") == '"hello world"'

    def test_value_with_double_quote_escaped(self):
        # Internal double quotes must be backslash-escaped
        assert escape_query_string('say "hi"') == '"say \\"hi\\""'

    def test_value_with_single_quote_quoted(self):
        # Single quotes also force quoting (server tokenizer)
        assert escape_query_string("it's") == "\"it's\""

    def test_control_chars_stripped_when_quoted(self):
        # When quoting is forced, control chars are dropped to prevent injection
        result = escape_query_string("a\x00b c")
        assert "\x00" not in result
        assert result == '"ab c"'

    def test_backslash_escaped(self):
        assert escape_query_string('a\\b c') == '"a\\\\b c"'

    def test_tab_triggers_quoting(self):
        result = escape_query_string("a\tb")
        assert result.startswith('"') and result.endswith('"')

    def test_lone_backslash_is_quoted(self):
        # The backslash is the tokenizer's escape character, so it is quoted
        # and escaped even without surrounding whitespace.
        assert escape_query_string("a\\b") == '"a\\\\b"'

    def test_parentheses_are_quoted(self):
        # Unquoted parentheses are grouping syntax to the expression parser.
        assert escape_query_string("(x)") == '"(x)"'

    def test_clause_keywords_are_quoted(self):
        # A literal query spelling a clause keyword must match as text rather
        # than open a clause the server then finds incomplete.
        assert escape_query_string("LIMIT") == '"LIMIT"'
        assert escape_query_string("and") == '"and"'
        assert escape_query_string("Order") == '"Order"'
        assert escape_query_string("android") == "android"


class TestQuoteCommandArgument:
    """quote_command_argument mirrors the C++ QuoteCommandArgumentIfNeeded."""

    def test_empty_returns_explicit_empty_token(self):
        assert quote_command_argument("", "value") == '""'

    def test_simple_passes_through_and_spaced_quoted(self):
        assert quote_command_argument("info", "value") == "info"
        assert quote_command_argument("two words", "value") == '"two words"'

    def test_lone_backslash_is_quoted(self):
        assert quote_command_argument("a\\b", "value") == '"a\\\\b"'

    def test_control_characters_rejected(self):
        with pytest.raises(InputValidationError):
            quote_command_argument("a\nb", "value")


class TestQualifyTableIdentity:
    def test_bare_table_when_no_database(self):
        assert qualify_table_identity("articles") == "articles"
        assert qualify_table_identity("articles", "") == "articles"

    def test_joins_database_and_table(self):
        assert qualify_table_identity("articles", "app_db") == "app_db.articles"

    def test_rejects_empty_table(self):
        with pytest.raises(InputValidationError):
            qualify_table_identity("")

    def test_rejects_whitespace_in_either_part(self):
        with pytest.raises(InputValidationError):
            qualify_table_identity("a b", "db")
        with pytest.raises(InputValidationError):
            qualify_table_identity("t", "a b")

    def test_rejects_dot_in_part_when_database_supplied(self):
        with pytest.raises(InputValidationError):
            qualify_table_identity("schema.articles", "app_db")
        with pytest.raises(InputValidationError):
            qualify_table_identity("articles", "a.b")


class TestParseTableIdentity:
    def test_bare_name_has_null_database(self):
        assert parse_table_identity("articles") == (None, "articles")

    def test_splits_qualified_identity_on_first_dot(self):
        assert parse_table_identity("app_db.articles") == ("app_db", "articles")

    def test_rejects_empty_halves(self):
        with pytest.raises(InputValidationError):
            parse_table_identity(".articles")
        with pytest.raises(InputValidationError):
            parse_table_identity("app_db.")

    def test_rejects_unsafe_identities(self):
        with pytest.raises(InputValidationError):
            parse_table_identity("")
        with pytest.raises(InputValidationError):
            parse_table_identity("a b")


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

    def test_open_tag_at_byte_cap_valid(self):
        tag = "a" * MAX_HIGHLIGHT_TAG_BYTES
        validate_highlight(HighlightOptions(open_tag=tag, close_tag="</em>"))

    def test_open_tag_over_byte_cap_rejected(self):
        tag = "a" * (MAX_HIGHLIGHT_TAG_BYTES + 1)
        with pytest.raises(InputValidationError, match="open_tag.*256 bytes"):
            validate_highlight(HighlightOptions(open_tag=tag, close_tag="</em>"))

    def test_close_tag_over_byte_cap_rejected(self):
        tag = "a" * (MAX_HIGHLIGHT_TAG_BYTES + 1)
        with pytest.raises(InputValidationError, match="close_tag.*256 bytes"):
            validate_highlight(HighlightOptions(open_tag="<em>", close_tag=tag))

    def test_tag_byte_cap_counts_utf8_bytes_not_chars(self):
        # Each U+3042 (HIRAGANA LETTER A) is 3 bytes in UTF-8, so 86 chars = 258 bytes,
        # which exceeds the 256-byte cap even though the character count is small.
        tag = "あ" * 86
        with pytest.raises(InputValidationError, match="open_tag.*256 bytes"):
            validate_highlight(HighlightOptions(open_tag=tag, close_tag="</em>"))


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
