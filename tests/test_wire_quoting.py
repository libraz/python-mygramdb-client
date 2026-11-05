"""
Tests for the shared wire-quoting helper (needs_wire_quoting / quote_wire_token
/ parse_wire_token). Mirrors mygram-db's src/client/wire_quoting.h decision.
"""
import pytest

from mygramdb_client.wire_quoting import (
    RESERVED_KEYWORDS,
    needs_wire_quoting,
    parse_wire_token,
    quote_wire_token,
)


class TestNeedsWireQuoting:
    def test_empty_needs_quoting(self):
        assert needs_wire_quoting("")

    def test_simple_word_does_not_need_quoting(self):
        assert not needs_wire_quoting("hello")

    @pytest.mark.parametrize("keyword", sorted(RESERVED_KEYWORDS))
    def test_reserved_keyword_needs_quoting_case_insensitively(self, keyword):
        assert needs_wire_quoting(keyword)
        assert needs_wire_quoting(keyword.lower())
        assert needs_wire_quoting(keyword.title())

    def test_ordinary_word_containing_keyword_substring_is_unaffected(self):
        assert not needs_wire_quoting("android")
        assert not needs_wire_quoting("ORDERLY".lower())

    @pytest.mark.parametrize(
        "ch", [" ", "\t", "\n", "\r", '"', "'", "\\", "(", ")"]
    )
    def test_ascii_special_chars_need_quoting(self, ch):
        assert needs_wire_quoting(f"a{ch}b")

    @pytest.mark.parametrize(
        "code",
        [0x0085, 0x00A0, 0x1680, 0x2000, 0x2001, 0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000],
    )
    def test_unicode_whitespace_needs_quoting(self, code):
        assert needs_wire_quoting(f"a{chr(code)}b")

    def test_zero_width_space_is_not_whitespace(self):
        # U+200B is not Unicode White_Space: the server keeps it inside a token.
        assert not needs_wire_quoting("a\u200bb")
        assert quote_wire_token("a\u200bb") == "a\u200bb"

    def test_nel_term_is_quoted_and_round_trips(self):
        quoted = quote_wire_token("a\x85b")
        assert quoted == '"a\x85b"'

    @pytest.mark.parametrize("value", ["a\"b", "it's", "a\\b"])
    def test_bare_token_with_quote_or_backslash_is_quoted(self, value):
        assert needs_wire_quoting(value)
        assert quote_wire_token(value).startswith('"')

    def test_non_ascii_latin_letters_ending_in_a0_or_85_are_not_split(self):
        # U+00E0 / U+00C5 share a trailing UTF-8 byte with NBSP / NEL.
        assert not needs_wire_quoting("caf\u00e0")
        assert not needs_wire_quoting("\u00c5ngstr\u00f6m")

    def test_control_char_needs_quoting(self):
        assert needs_wire_quoting("a\x01b")


class TestQuoteWireToken:
    def test_unchanged_when_not_needed(self):
        assert quote_wire_token("hello") == "hello"
        assert quote_wire_token("こんにちは") == "こんにちは"

    def test_empty_becomes_explicit_empty_token(self):
        assert quote_wire_token("") == '""'

    def test_reserved_keyword_quoted(self):
        assert quote_wire_token("AND") == '"AND"'
        assert quote_wire_token("order") == '"order"'

    def test_unicode_whitespace_term_quoted_and_round_trips(self):
        # Full-width space (U+3000): unquoted this would split into two
        # tokens on the server's tokenizer.
        value = "東京　タワー"
        quoted = quote_wire_token(value)
        assert quoted == f'"{value}"'
        parsed = parse_wire_token(quoted, 0)
        assert parsed == (value, len(quoted))

    def test_nbsp_term_quoted(self):
        value = "a b"
        quoted = quote_wire_token(value)
        assert quoted.startswith('"') and quoted.endswith('"')
        assert parse_wire_token(quoted, 0) == (value, len(quoted))

    def test_backslash_and_quote_escaped(self):
        assert quote_wire_token('say "hi"') == '"say \\"hi\\""'
        assert quote_wire_token("a\\b") == '"a\\\\b"'

    def test_common_control_chars_use_named_escapes(self):
        assert quote_wire_token("a\rb") == '"a\\rb"'
        assert quote_wire_token("a\nb") == '"a\\nb"'
        assert quote_wire_token("a\tb") == '"a\\tb"'

    def test_other_control_bytes_escaped_as_hex(self):
        assert quote_wire_token("a\x01b") == '"a\\x01b"'
        assert quote_wire_token("a\x00b") == '"a\\x00b"'

    def test_parens_quoted(self):
        assert quote_wire_token("(x)") == '"(x)"'


class TestParseWireToken:
    def test_bare_token(self):
        assert parse_wire_token("hello world", 0) == ("hello", 5)

    def test_skips_leading_whitespace(self):
        assert parse_wire_token("   hello", 0) == ("hello", 8)

    def test_nothing_left_returns_none(self):
        assert parse_wire_token("   ", 0) is None
        assert parse_wire_token("", 0) is None

    def test_quoted_token_with_space(self):
        assert parse_wire_token('"a b" rest', 0) == ("a b", 5)

    def test_quoted_token_with_escapes(self):
        assert parse_wire_token('"a\\"b\\\\c" x', 0) == ('a"b\\c', 9)

    def test_quoted_token_with_hex_escape(self):
        assert parse_wire_token('"a\\x01b"', 0) == ("a\x01b", 8)

    def test_unterminated_quote_returns_none(self):
        assert parse_wire_token('"unterminated', 0) is None

    def test_truncated_hex_escape_returns_none(self):
        assert parse_wire_token('"a\\x1"', 0) is None

    def test_round_trips_with_quote_wire_token(self):
        for value in ["plain", "", "AND", "a b", '"quoted"', "a\\b", "line1\nline2"]:
            quoted = quote_wire_token(value)
            parsed = parse_wire_token(quoted, 0)
            assert parsed is not None
            assert parsed[0] == value


class TestQuotedPrimaryKeyRoundTrip:
    """A primary key containing a space survives quoting and decoding intact."""

    def test_primary_key_with_space(self):
        pk = "New York"
        wire = quote_wire_token(pk)
        assert wire == '"New York"'
        # As it would appear inline among other tokens on a SEARCH header line.
        header = f'OK RESULTS 1 {wire}'
        pos = header.index(wire)
        parsed = parse_wire_token(header, pos)
        assert parsed is not None
        assert parsed[0] == pk
