"""Tests for command validation utilities."""
import pytest

from mygramdb_client.command_utils import (
    calculate_query_expression_length,
    ensure_query_length_within_limit,
    ensure_safe_command_value,
    ensure_safe_filters,
    ensure_safe_string_array,
    has_control_characters,
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
