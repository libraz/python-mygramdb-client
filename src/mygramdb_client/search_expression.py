"""
Web-style search expression parser (+/- syntax).

Converts web-style search expressions into MygramDB query format.

Syntax:
- `+term` - Required term (must appear)
- `-term` - Excluded term (must not appear)
- `term1 term2` - Multiple terms (implicit AND)
- `"phrase"` - Quoted phrase (exact match with spaces)
- `(expr)` - Grouping
- `OR` - Logical OR between terms

Examples:
- `golang tutorial` -> `golang AND tutorial` (implicit AND)
- `"machine learning" tutorial` -> `"machine learning" AND tutorial`
- `golang -old` -> `golang AND NOT old`
- `python OR ruby` -> `(python OR ruby)`
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from .types import SimplifiedExpression


class TokenType(Enum):
    """Token types for expression parsing."""

    WORD = "WORD"
    QUOTED = "QUOTED"
    PLUS = "PLUS"
    MINUS = "MINUS"
    OR = "OR"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    EOF = "EOF"


@dataclass
class Token:
    """A token from the search expression."""

    type: TokenType
    value: str
    position: int


@dataclass
class SearchExpression:
    """Parsed search expression components."""

    required_terms: List[str] = field(default_factory=list)
    excluded_terms: List[str] = field(default_factory=list)
    optional_terms: List[str] = field(default_factory=list)
    raw_expression: str = ""


class Tokenizer:
    """Tokenizer for search expressions."""

    def __init__(self, input_str: str):
        # Normalize full-width spaces to half-width (U+3000)
        self.input = input_str.replace("\u3000", " ")
        self.position = 0
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        """Tokenize the input string."""
        while self.position < len(self.input):
            self._skip_whitespace()
            if self.position >= len(self.input):
                break

            char = self.input[self.position]

            if char == "+":
                self.tokens.append(
                    Token(TokenType.PLUS, "+", self.position)
                )
                self.position += 1
            elif char == "-":
                self.tokens.append(
                    Token(TokenType.MINUS, "-", self.position)
                )
                self.position += 1
            elif char == "(":
                self.tokens.append(
                    Token(TokenType.LPAREN, "(", self.position)
                )
                self.position += 1
            elif char == ")":
                self.tokens.append(
                    Token(TokenType.RPAREN, ")", self.position)
                )
                self.position += 1
            elif char == '"':
                self._tokenize_quoted()
            else:
                self._tokenize_word()

        self.tokens.append(Token(TokenType.EOF, "", self.position))
        return self.tokens

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.position < len(self.input) and self.input[self.position].isspace():
            self.position += 1

    def _tokenize_quoted(self) -> None:
        """Tokenize a quoted string."""
        start = self.position
        self.position += 1  # Skip opening quote

        value = ""
        while self.position < len(self.input) and self.input[self.position] != '"':
            value += self.input[self.position]
            self.position += 1

        if self.position >= len(self.input):
            raise ValueError(f"Unterminated quoted string at position {start}")

        self.position += 1  # Skip closing quote
        self.tokens.append(Token(TokenType.QUOTED, value, start))

    def _tokenize_word(self) -> None:
        """Tokenize a word."""
        start = self.position
        value = ""
        special_chars = set(' \t\n\r+-()\"')

        while (
            self.position < len(self.input)
            and self.input[self.position] not in special_chars
        ):
            value += self.input[self.position]
            self.position += 1

        if value.upper() == "OR":
            self.tokens.append(Token(TokenType.OR, "OR", start))
        else:
            self.tokens.append(Token(TokenType.WORD, value, start))


def parse_search_expression(expression: str) -> SearchExpression:
    """
    Parse web-style search expression.

    Converts expressions like "+golang -old (tutorial OR guide)" into
    structured format.

    Args:
        expression: Web-style search expression.

    Returns:
        Parsed expression components.

    Raises:
        ValueError: If expression is invalid.
    """
    if not expression or not expression.strip():
        raise ValueError("Search expression cannot be empty")

    tokenizer = Tokenizer(expression)
    tokens = tokenizer.tokenize()

    result = SearchExpression(raw_expression=expression)
    has_complex_expr = False

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.type == TokenType.EOF:
            break

        if token.type == TokenType.PLUS:
            # Required term or grouped expression
            if i + 1 >= len(tokens):
                raise ValueError(
                    f"Expected term after '+' at position {token.position}"
                )
            next_token = tokens[i + 1]

            if next_token.type == TokenType.LPAREN:
                # Grouped expression - mark as complex
                has_complex_expr = True
                i += 1  # Skip the opening paren
            elif next_token.type in (TokenType.WORD, TokenType.QUOTED):
                # Add quotes back for quoted terms (phrase search)
                term = (
                    f'"{next_token.value}"'
                    if next_token.type == TokenType.QUOTED
                    else next_token.value
                )
                result.required_terms.append(term)
                i += 1  # Skip the term we just processed
            else:
                raise ValueError(
                    f"Expected term after '+' at position {token.position}"
                )

        elif token.type == TokenType.MINUS:
            # Excluded term
            if i + 1 >= len(tokens):
                raise ValueError(
                    f"Expected term after '-' at position {token.position}"
                )
            next_token = tokens[i + 1]

            if next_token.type not in (TokenType.WORD, TokenType.QUOTED):
                raise ValueError(
                    f"Expected term after '-' at position {token.position}"
                )
            # Add quotes back for quoted terms (phrase search)
            term = (
                f'"{next_token.value}"'
                if next_token.type == TokenType.QUOTED
                else next_token.value
            )
            result.excluded_terms.append(term)
            i += 1  # Skip the term we just processed

        elif token.type in (TokenType.WORD, TokenType.QUOTED):
            # Optional term (no prefix) - add quotes back for quoted terms
            term = (
                f'"{token.value}"'
                if token.type == TokenType.QUOTED
                else token.value
            )
            result.optional_terms.append(term)

        elif token.type in (TokenType.OR, TokenType.LPAREN, TokenType.RPAREN):
            has_complex_expr = True

        i += 1

    # If we have complex expressions (OR, grouping), we keep the raw expression
    # Otherwise, we can simplify
    if not has_complex_expr:
        result.raw_expression = ""

    return result


def has_complex_expression(expr: SearchExpression) -> bool:
    """
    Check if expression has OR operators or grouping.

    Args:
        expr: Parsed search expression.

    Returns:
        True if expression has OR operators or grouping.
    """
    return bool(
        expr.raw_expression
        and ("OR" in expr.raw_expression or "(" in expr.raw_expression)
    )


def to_query_string(expr: SearchExpression) -> str:
    """
    Convert search expression to query string.

    Generates proper boolean query string:
    - Required terms: joined with AND
    - Excluded terms: prefixed with NOT
    - Optional terms: joined with OR (if no required terms)

    Args:
        expr: Parsed search expression.

    Returns:
        Query string.
    """
    parts: List[str] = []

    # Add required terms
    if expr.required_terms:
        parts.append(" AND ".join(expr.required_terms))

    # Add optional terms
    if expr.optional_terms:
        if not expr.required_terms:
            # No required terms, treat optional as OR
            parts.append(" OR ".join(expr.optional_terms))
        else:
            # Has required terms, treat optional as AND
            parts.append(" AND ".join(expr.optional_terms))

    # Add excluded terms
    if expr.excluded_terms:
        parts.append(
            " AND ".join(f"NOT {term}" for term in expr.excluded_terms)
        )

    return " AND ".join(parts)


def convert_search_expression(expression: str) -> str:
    """
    Convert search expression directly to QueryAST-compatible string.

    This is a convenience function that combines parse_search_expression
    and to_query_string() in one call.

    Examples:
    - `+golang tutorial` -> `golang AND tutorial`
    - `+golang -old` -> `golang AND NOT old`
    - `python OR ruby` -> `python OR ruby`  (complex expression returned as-is)

    Args:
        expression: Web-style search expression.

    Returns:
        QueryAST-compatible query string.

    Raises:
        ValueError: If expression is invalid.
    """
    expr = parse_search_expression(expression)

    # If has complex expression with OR/grouping, return as-is
    if has_complex_expression(expr):
        return expr.raw_expression

    return to_query_string(expr)


def simplify_search_expression(expression: str) -> SimplifiedExpression:
    """
    Simplify search expression to basic terms.

    For clients that don't support full QueryAST, this extracts simple term
    lists. Required (``+``) terms are surfaced as ``main_term`` plus
    ``and_terms``; OR-only or parenthesized sub-expressions (e.g.
    ``python OR ruby`` or ``(a OR b)``) are surfaced as a single
    parenthesized ``main_term`` so the OR semantics survive when the caller
    AND-composes the result.

    Examples:
    - ``+golang -old`` -> main_term=``golang``, not_terms=[``old``]
    - ``python OR ruby`` -> main_term=``(python OR ruby)``
    - ``(python OR ruby)`` -> main_term=``(python OR ruby)`` (not double-wrapped)

    Args:
        expression: Web-style search expression.

    Returns:
        Simplified expression with main_term, and_terms, and not_terms.

    Raises:
        ValueError: If expression is invalid or has no positive terms.
    """
    expr = parse_search_expression(expression)

    # Complex expression (OR / parenthesized): the optional_terms list
    # contains the inside of OR sub-expressions, which would lose meaning
    # if flattened into AND. Surface the raw expression instead.
    if has_complex_expression(expr):
        if expr.required_terms:
            # Mixed (e.g. "+golang (tutorial OR guide)"): keep the required
            # terms; the OR sub-expression is currently not surfaced.
            return SimplifiedExpression(
                main_term=expr.required_terms[0],
                and_terms=list(expr.required_terms[1:]),
                not_terms=list(expr.excluded_terms),
            )

        raw = expr.raw_expression.strip()
        if raw.startswith("(") and raw.endswith(")"):
            main_term = raw
        else:
            main_term = f"({raw})"
        return SimplifiedExpression(
            main_term=main_term,
            and_terms=[],
            not_terms=list(expr.excluded_terms),
        )

    # Simple expression: combine required + optional (the implicit AND case).
    all_positive_terms = expr.required_terms + expr.optional_terms
    if not all_positive_terms:
        raise ValueError("Search expression must have at least one positive term")

    return SimplifiedExpression(
        main_term=all_positive_terms[0],
        and_terms=list(all_positive_terms[1:]),
        not_terms=list(expr.excluded_terms),
    )
