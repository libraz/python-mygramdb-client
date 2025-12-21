"""Command validation utilities for MygramDB client."""
import re
from typing import Dict, List, Optional

from .errors import InputValidationError

# Control characters: 0x00-0x1F and 0x7F
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x1f\x7f]')


def has_control_characters(value: str) -> bool:
    """Check if a string contains control characters."""
    return bool(CONTROL_CHAR_PATTERN.search(value))


def ensure_safe_command_value(value: str, field_name: str) -> None:
    """
    Validate that a value does not contain control characters.

    Args:
        value: The value to validate.
        field_name: Name of the field for error messages.

    Raises:
        InputValidationError: If value contains control characters.
    """
    if has_control_characters(value):
        raise InputValidationError(
            f"{field_name} contains invalid control characters"
        )


def ensure_safe_string_array(values: List[str], field_name: str) -> None:
    """
    Validate that all values in a list do not contain control characters.

    Args:
        values: List of values to validate.
        field_name: Name of the field for error messages.

    Raises:
        InputValidationError: If any value contains control characters.
    """
    for i, value in enumerate(values):
        if has_control_characters(value):
            raise InputValidationError(
                f"{field_name}[{i}] contains invalid control characters"
            )


def ensure_safe_filters(filters: Dict[str, str]) -> None:
    """
    Validate that filter keys and values do not contain control characters.

    Args:
        filters: Dictionary of filter key-value pairs.

    Raises:
        InputValidationError: If any key or value contains control characters.
    """
    for key, value in filters.items():
        if has_control_characters(key):
            raise InputValidationError(
                f"Filter key '{key}' contains invalid control characters"
            )
        if has_control_characters(value):
            raise InputValidationError(
                f"Filter value for '{key}' contains invalid control characters"
            )


def calculate_query_expression_length(
    query: str,
    and_terms: Optional[List[str]] = None,
    not_terms: Optional[List[str]] = None,
) -> int:
    """
    Calculate the total length of a query expression.

    Args:
        query: The main query string.
        and_terms: Optional list of AND terms.
        not_terms: Optional list of NOT terms.

    Returns:
        Total character length of the expression.
    """
    total = len(query)

    if and_terms:
        for term in and_terms:
            total += len(term)

    if not_terms:
        for term in not_terms:
            total += len(term)

    return total


def ensure_query_length_within_limit(
    query: str,
    max_length: int,
    and_terms: Optional[List[str]] = None,
    not_terms: Optional[List[str]] = None,
) -> None:
    """
    Validate that the total query expression length is within the limit.

    Args:
        query: The main query string.
        max_length: Maximum allowed length.
        and_terms: Optional list of AND terms.
        not_terms: Optional list of NOT terms.

    Raises:
        InputValidationError: If total length exceeds maximum.
    """
    total_length = calculate_query_expression_length(query, and_terms, not_terms)

    if total_length > max_length:
        raise InputValidationError(
            f"Query expression length ({total_length}) exceeds "
            f"maximum allowed length ({max_length})"
        )


def validate_table_name(table: str) -> None:
    """
    Validate a table name.

    Args:
        table: The table name to validate.

    Raises:
        InputValidationError: If table name is invalid.
    """
    if not table:
        raise InputValidationError("Table name cannot be empty")

    ensure_safe_command_value(table, "table")


def validate_primary_key(primary_key: str) -> None:
    """
    Validate a primary key.

    Args:
        primary_key: The primary key to validate.

    Raises:
        InputValidationError: If primary key is invalid.
    """
    if not primary_key:
        raise InputValidationError("Primary key cannot be empty")

    ensure_safe_command_value(primary_key, "primaryKey")
