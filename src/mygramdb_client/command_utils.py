"""Command validation utilities for MygramDB client."""
import re
from typing import Dict, List, Optional

from .errors import InputValidationError
from .types import HighlightOptions

# Control characters: 0x00-0x1F and 0x7F
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x1f\x7f]')

# Whitespace characters that would split an unquoted identifier into multiple tokens
_IDENTIFIER_WHITESPACE = (" ", "\t", "\n", "\r", "\v", "\f")

# Characters that force a query/value to be quoted on the wire
_QUOTE_TRIGGER_CHARS = frozenset({" ", "\t", "\n", "\r", '"', "'"})

# Maximum byte length for HIGHLIGHT open_tag / close_tag values. Mirrors the
# server-side cap (kMaxHighlightTagLength) introduced to prevent response-size
# amplification from crafted tag values.
MAX_HIGHLIGHT_TAG_BYTES = 256


def has_control_characters(value: str) -> bool:
    """Check if a string contains control characters."""
    return bool(CONTROL_CHAR_PATTERN.search(value))


def validate_identifier(value: str, field_name: str) -> None:
    """
    Validate an unquoted identifier (table, primary key, sort column, filter key).

    Identifiers are sent on the wire without quoting; embedded whitespace would
    split them into multiple tokens and corrupt the protocol.

    Args:
        value: Identifier value.
        field_name: Human-readable field name for error messages.

    Raises:
        InputValidationError: If value is empty or contains whitespace/control chars.
    """
    if value == "":
        raise InputValidationError(f"Input for {field_name} is empty")
    for ch in value:
        code = ord(ch)
        if (0x00 <= code <= 0x1F) or code == 0x7F:
            raise InputValidationError(
                f"Input for {field_name} contains control character "
                f"0x{code:02X}, which is not allowed"
            )
        if ch in _IDENTIFIER_WHITESPACE:
            raise InputValidationError(
                f"Input for {field_name} contains whitespace, "
                "which is not allowed in identifiers"
            )


def _quote_token_if_needed(value: str, quote_on_backslash: bool) -> str:
    """
    Wrap a value in double quotes when it would otherwise split into multiple
    protocol tokens, escaping the characters that are special inside a quoted
    token.

    Mirrors the C++ client's ``EscapeQueryString`` / ``QuoteCommandArgumentIfNeeded``:
    a value is quoted when it is empty or contains whitespace or a quote
    character. Inside the quotes, ``"`` and ``\\`` are backslash-escaped and any
    remaining control characters (code < 0x20) are dropped. Values that need no
    quoting are returned verbatim so simple single-token queries stay
    byte-identical on the wire.

    ``quote_on_backslash`` selects which upstream helper is mirrored: query
    strings follow ``EscapeQueryString`` (a lone backslash does NOT force
    quoting), while command arguments follow ``QuoteCommandArgumentIfNeeded``
    (a backslash does).

    Args:
        value: Value to quote (already control-char validated by the caller).
        quote_on_backslash: Whether a lone ``\\`` forces quoting.

    Returns:
        Wire-safe single token.
    """
    if value == "":
        return '""'

    needs_quotes = any(
        ch in _QUOTE_TRIGGER_CHARS or (quote_on_backslash and ch == "\\")
        for ch in value
    )
    if not needs_quotes:
        return value

    out = ['"']
    for ch in value:
        if ord(ch) < 0x20:
            # Drop control characters to prevent command injection.
            continue
        if ch == '"' or ch == "\\":
            out.append("\\")
        out.append(ch)
    out.append('"')
    return "".join(out)


def escape_query_string(value: str) -> str:
    """
    Quote and escape a free-form value for use as a wire token.

    Empty strings are emitted as the explicit ``""`` token to keep the wire
    form unambiguous: an unquoted empty arg would collapse into surrounding
    whitespace and produce a malformed command (e.g. ``SEARCH table  AND foo``).

    Values containing whitespace, double quotes or single quotes are wrapped
    in double quotes with internal quotes/backslashes escaped. Control
    characters are stripped to prevent command injection. Matches the C++
    client's ``EscapeQueryString`` (a lone backslash does not force quoting).
    """
    return _quote_token_if_needed(value, quote_on_backslash=False)


def quote_command_argument(value: str, field_name: str) -> str:
    """
    Quote a free-form command argument (e.g. a ``SET`` value, a
    ``SHOW VARIABLES LIKE`` pattern or a ``DUMP`` filepath) when it contains
    whitespace or quote characters. Mirrors the C++ client's
    ``QuoteCommandArgumentIfNeeded``.

    Unlike :func:`escape_query_string`, a lone backslash forces quoting and the
    value is validated for control characters (which would otherwise be
    silently dropped). An empty value is allowed and surfaced as the explicit
    empty token ``""``.

    Args:
        value: Argument value.
        field_name: Field name for clearer error messages.

    Returns:
        Wire-safe single token.

    Raises:
        InputValidationError: When the value contains control characters.
    """
    if value != "":
        ensure_safe_command_value(value, field_name)
    return _quote_token_if_needed(value, quote_on_backslash=True)


def qualify_table_identity(table: str, database: Optional[str] = None) -> str:
    """
    Build a database-qualified table identity (``database.table``) for MygramDB
    v1.7+ multi-database deployments.

    A single-database deployment continues to accept a bare table name, so an
    empty/omitted ``database`` returns just the validated table name. When a
    database is supplied, both parts are validated as identifiers and must not
    themselves contain a ``.`` separator; they are then joined as
    ``database.table``.

    Args:
        table: Bare table name.
        database: Owning database (empty/omitted for single-db).

    Returns:
        ``database.table``, or ``table`` when no database is given.

    Raises:
        InputValidationError: When either part is empty, contains
            whitespace/control characters, or embeds a ``.`` separator.

    Example:
        >>> qualify_table_identity("articles")
        'articles'
        >>> qualify_table_identity("articles", "app_db")
        'app_db.articles'
    """
    validate_identifier(table, "table")
    if database is None or database == "":
        return table
    validate_identifier(database, "database")
    if "." in database:
        raise InputValidationError(
            "Input for database must not contain a '.' separator"
        )
    if "." in table:
        raise InputValidationError(
            "Input for table must not contain a '.' when a database is "
            "supplied separately"
        )
    return f"{database}.{table}"


def parse_table_identity(identity: str) -> "tuple[Optional[str], str]":
    """
    Split a (possibly database-qualified) table identity into its parts.

    Bare names return ``(None, table)``; qualified names are split on the first
    ``.`` so ``app_db.articles`` yields ``("app_db", "articles")``. The identity
    is validated as a protocol identifier first.

    Args:
        identity: ``database.table`` or a bare ``table``.

    Returns:
        A ``(database, table)`` tuple; ``database`` is ``None`` for bare names.

    Raises:
        InputValidationError: When the identity is empty/unsafe or has an empty
            database or table half.
    """
    validate_identifier(identity, "table")
    dot = identity.find(".")
    if dot == -1:
        return (None, identity)
    database = identity[:dot]
    table = identity[dot + 1:]
    if database == "" or table == "":
        raise InputValidationError(
            f'Invalid table identity "{identity}": expected <database>.<table>'
        )
    return (database, table)


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

    Table names are sent unquoted on the wire so they must not contain
    whitespace or control characters.

    Args:
        table: The table name to validate.

    Raises:
        InputValidationError: If table name is invalid.
    """
    if not table:
        raise InputValidationError("Table name cannot be empty")

    ensure_safe_command_value(table, "table")
    for ch in table:
        if ch in _IDENTIFIER_WHITESPACE:
            raise InputValidationError(
                "Table name contains whitespace, which is not allowed"
            )


def validate_fuzzy(distance: int) -> None:
    """
    Validate a FUZZY edit distance. Accepts 0 (disables), 1 or 2.

    Args:
        distance: Fuzzy edit distance.

    Raises:
        InputValidationError: If distance is outside {0, 1, 2}.
    """
    if distance in (0, 1, 2):
        return
    raise InputValidationError(
        f"Invalid fuzzy distance {distance}: must be 0, 1, or 2"
    )


def validate_highlight(highlight: Optional[HighlightOptions]) -> None:
    """
    Validate HIGHLIGHT clause options.

    ``open_tag``/``close_tag`` must both be empty or both be set, contain no
    control or whitespace characters, and each must be at most
    ``MAX_HIGHLIGHT_TAG_BYTES`` (256) bytes when UTF-8 encoded.
    ``snippet_len``/``max_fragments`` must fall within the documented ranges.

    Args:
        highlight: Highlight options to validate (no-op when ``None``).

    Raises:
        InputValidationError: When options are invalid.
    """
    if highlight is None:
        return

    open_tag = highlight.open_tag or ""
    close_tag = highlight.close_tag or ""
    if (open_tag == "") != (close_tag == ""):
        raise InputValidationError(
            "highlight open_tag and close_tag must be set together"
        )

    for name, value in (("highlight.open_tag", open_tag),
                        ("highlight.close_tag", close_tag)):
        if value == "":
            continue
        ensure_safe_command_value(value, name)
        for ch in value:
            if ch == " " or ch == "\t":
                raise InputValidationError(
                    f"{name} must not contain whitespace: {value!r}"
                )
        encoded_len = len(value.encode("utf-8"))
        if encoded_len > MAX_HIGHLIGHT_TAG_BYTES:
            raise InputValidationError(
                f"{name} must not exceed {MAX_HIGHLIGHT_TAG_BYTES} bytes "
                f"(got {encoded_len})"
            )

    snippet_len = highlight.snippet_len or 0
    if snippet_len < 0 or snippet_len > 10000:
        raise InputValidationError(
            f"highlight.snippet_len out of range (0..10000): {snippet_len}"
        )

    max_fragments = highlight.max_fragments or 0
    if max_fragments < 0 or max_fragments > 100:
        raise InputValidationError(
            f"highlight.max_fragments out of range (0..100): {max_fragments}"
        )


def validate_facet_column(column: str) -> None:
    """
    Validate a FACET column name.

    Same rules as table names: must be non-empty and contain no control
    or whitespace characters.

    Args:
        column: Column name.

    Raises:
        InputValidationError: If column name is invalid.
    """
    if column == "":
        raise InputValidationError("facet column must not be empty")
    for ch in column:
        code = ord(ch)
        if (0x00 <= code <= 0x1F) or code == 0x7F or ch == " " or ch == "\t":
            raise InputValidationError(
                f"facet column contains invalid character: {ch!r}"
            )


def validate_primary_key(primary_key: str) -> None:
    """
    Validate a primary key.

    Primary keys are sent unquoted on the wire so they must not contain
    whitespace or control characters.

    Args:
        primary_key: The primary key to validate.

    Raises:
        InputValidationError: If primary key is invalid.
    """
    if not primary_key:
        raise InputValidationError("Primary key cannot be empty")

    ensure_safe_command_value(primary_key, "primaryKey")
    for ch in primary_key:
        if ch in _IDENTIFIER_WHITESPACE:
            raise InputValidationError(
                "Primary key contains whitespace, which is not allowed"
            )
