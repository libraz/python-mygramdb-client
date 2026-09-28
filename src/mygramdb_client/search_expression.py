"""
Web-style search expression parser (+/- syntax).

Converts web-style search expressions into MygramDB query format. Mirrors
the C++ client's ``src/client/search_expression.cpp``.

Syntax:
- `+term` - Required term (must appear)
- `-term` - Excluded term (must not appear)
- `term1 term2` - Multiple terms, unprefixed or prefixed alike (implicit AND)
- `"phrase"` - Quoted phrase (exact match with spaces)
- `(expr)` - Grouping
- `OR` - Logical OR between terms

Examples:
- `golang tutorial` -> `golang AND tutorial` (implicit AND)
- `"machine learning" tutorial` -> `"machine learning" AND tutorial`
- `golang -old` -> `golang AND NOT old`
- `python OR ruby` -> `(python OR ruby)`
- `golang +(tutorial OR guide)` -> `golang AND (tutorial OR guide)`
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional

from .types import SimplifiedExpression
from .wire_quoting import quote_wire_token, is_wire_whitespace


class TokenType(Enum):
    """Token types for expression parsing."""

    TERM = auto()
    QUOTED_TERM = auto()
    PLUS = auto()
    MINUS = auto()
    OR = auto()
    LPAREN = auto()
    RPAREN = auto()
    END = auto()


@dataclass
class Token:
    """A token from the search expression."""

    type: TokenType
    value: str = ""


@dataclass
class SearchExpression:
    """Parsed search expression components."""

    required_terms: List[str] = field(default_factory=list)
    excluded_terms: List[str] = field(default_factory=list)
    optional_terms: List[str] = field(default_factory=list)
    """Unused; kept for source compatibility. Every unprefixed term is
    required (implicit AND) and lands in :attr:`required_terms`."""
    raw_expression: str = ""
    """Formatted AST-syntax text for a bare OR/grouped sub-expression."""


def _is_ascii_alnum(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9")


def _is_paren_subexpression(term: str) -> bool:
    """
    Check whether a required/excluded term is a parenthesized sub-expression.

    A parenthesized expression following unary +/- (already fully
    quoted/escaped) is retained as one required/excluded-term entry instead
    of being folded into ``raw_expression``. Detecting that structural
    representation this way -- never by scanning for an "OR" substring
    inside a token, which would misclassify ordinary words such as ORDER
    and ORANGE -- lets :func:`has_complex_expression` and
    :func:`to_query_string` agree on which entries are already
    wire-formatted and which are plain terms still needing
    :func:`~.wire_quoting.quote_wire_token`.
    """
    return len(term) >= 2 and term[0] == "(" and term[-1] == ")"


class Tokenizer:
    """Tokenizer for search expressions."""

    def __init__(self, input_str: str):
        self.input = input_str
        self.pos = 0

    def get_position(self) -> int:
        return self.pos

    def set_position(self, pos: int) -> None:
        self.pos = pos

    def next(self) -> Token:
        """Get the next token."""
        self._skip_whitespace()

        if self.pos >= len(self.input):
            return Token(TokenType.END)

        ch = self.input[self.pos]

        if ch == '"':
            return Token(TokenType.QUOTED_TERM, self._read_quoted_string())
        if ch == "+":
            self.pos += 1
            return Token(TokenType.PLUS)
        if ch == "-":
            self.pos += 1
            return Token(TokenType.MINUS)
        if ch == "(":
            self.pos += 1
            return Token(TokenType.LPAREN)
        if ch == ")":
            self.pos += 1
            return Token(TokenType.RPAREN)

        # OR operator, recognized case-insensitively as a whole word (never
        # as a substring of an ordinary word such as ORDER or ORANGE). Word
        # boundaries are checked against ASCII alnum only, matching the
        # server's own case-insensitive OR recognition.
        if (
            self.pos + 2 <= len(self.input)
            and self.input[self.pos].upper() == "O"
            and self.input[self.pos + 1].upper() == "R"
        ):
            before_ok = self.pos == 0 or not _is_ascii_alnum(self.input[self.pos - 1])
            after_ok = (
                self.pos + 2 >= len(self.input) or not _is_ascii_alnum(self.input[self.pos + 2])
            )
            if before_ok and after_ok:
                self.pos += 2
                return Token(TokenType.OR, "OR")

        return Token(TokenType.TERM, self._read_term())

    def _skip_whitespace(self) -> None:
        while self.pos < len(self.input) and is_wire_whitespace(self.input[self.pos]):
            self.pos += 1

    def _read_term(self) -> str:
        # '+' and '-' are unary operators only when next() sees them at a
        # token boundary. Once a term has started they are ordinary text, as
        # in "COVID-19", "e-mail" and "C++".
        start = self.pos
        while self.pos < len(self.input):
            ch = self.input[self.pos]
            if is_wire_whitespace(ch) or ch in "()\"":
                break
            self.pos += 1
        return self.input[start:self.pos]

    def _read_quoted_string(self) -> str:
        start = self.pos
        self.pos += 1  # skip opening quote
        chars: List[str] = []
        while self.pos < len(self.input):
            ch = self.input[self.pos]
            if ch == '"':
                self.pos += 1
                return "".join(chars)
            if ch == "\\" and self.pos + 1 < len(self.input):
                self.pos += 1
                chars.append(self.input[self.pos])
                self.pos += 1
            else:
                chars.append(ch)
                self.pos += 1
        raise ValueError(f"Unterminated quoted string at position {start}")


class _Parser:
    """Recursive-descent parser for search expressions."""

    def __init__(self, text: str):
        self._tokenizer = Tokenizer(text)
        self._current = self._tokenizer.next()

    def _advance(self) -> None:
        self._current = self._tokenizer.next()

    def parse(self) -> SearchExpression:
        expr = SearchExpression()

        while self._current.type != TokenType.END:
            if self._current.type == TokenType.PLUS:
                self._advance()
                term = self._parse_prefixed_term()
                if term is None:
                    raise ValueError("Expected term after '+'")
                expr.required_terms.append(term)
            elif self._current.type == TokenType.MINUS:
                self._advance()
                term = self._parse_prefixed_term()
                if term is None:
                    raise ValueError("Expected term after '-'")
                expr.excluded_terms.append(term)
            elif self._current.type == TokenType.LPAREN:
                paren_expr = self._capture_paren_expression()
                if not paren_expr:
                    raise ValueError("Unbalanced parentheses")
                if expr.raw_expression:
                    expr.raw_expression += " "
                expr.raw_expression += paren_expr
            elif self._current.type in (TokenType.TERM, TokenType.QUOTED_TERM):
                if self._looks_like_or_expression():
                    or_expr = self._capture_or_expression()
                    if expr.raw_expression:
                        expr.raw_expression += " "
                    expr.raw_expression += or_expr
                else:
                    # Stored as plain text regardless of whether it was
                    # quoted -- to_query_string/simplify_search_expression
                    # each apply the shared wire-quoting decision exactly
                    # once, at whichever destination the term is serialized.
                    expr.required_terms.append(self._current.value)
                    self._advance()
            elif self._current.type == TokenType.OR:
                raise ValueError("Unexpected 'OR' operator")
            elif self._current.type == TokenType.RPAREN:
                raise ValueError("Unexpected ')'")
            else:
                self._advance()

        return expr

    def _parse_prefixed_term(self) -> Optional[str]:
        if self._current.type == TokenType.LPAREN:
            expr = self._capture_paren_expression()
            return expr if expr else None
        if self._current.type in (TokenType.TERM, TokenType.QUOTED_TERM):
            term = self._current.value
            self._advance()
            return term
        return None

    def _looks_like_or_expression(self) -> bool:
        saved_pos = self._tokenizer.get_position()
        saved_current = self._current
        self._advance()  # skip current term
        has_or = self._current.type == TokenType.OR
        self._tokenizer.set_position(saved_pos)
        self._current = saved_current
        return has_or

    def _capture_or_expression(self) -> str:
        # Every term (quoted or not) goes through the same wire-quoting
        # decision as to_query_string's required/excluded terms, so a plain
        # word colliding with a reserved keyword (e.g. "order") is quoted
        # here too instead of reaching the AST parser as a bare operator.
        parts = [quote_wire_token(self._current.value)]
        self._advance()

        while self._current.type == TokenType.OR:
            self._advance()
            if self._current.type in (TokenType.TERM, TokenType.QUOTED_TERM):
                parts.append(quote_wire_token(self._current.value))
                self._advance()
            elif self._current.type == TokenType.LPAREN:
                paren = self._capture_paren_expression()
                if not paren:
                    raise ValueError("Unbalanced parentheses after 'OR'")
                parts.append(paren)
            else:
                raise ValueError("Expected term after 'OR'")

        return " OR ".join(parts)

    def _capture_paren_expression(self) -> str:
        if self._current.type != TokenType.LPAREN:
            return ""

        parts: List[str] = []
        depth = 0
        # Tracks the last *content* token type (term/quoted-term/paren/OR) so
        # the spacing decision below is unaffected by a +/- prefix in
        # between -- otherwise "tutorial -video" would skip the space it
        # needs before the "NOT" it is about to emit.
        previous_type: Optional[TokenType] = None
        # A bare '-' has no keyword the AST parser recognizes; the server
        # only understands the literal word NOT. Defer emission until the
        # term it prefixes arrives, exactly as excluded_terms outside a
        # group are rendered as "NOT term" in to_query_string.
        pending_not = False

        while True:
            if self._current.type == TokenType.LPAREN:
                depth += 1
                parts.append("(")
                previous_type = TokenType.LPAREN
            elif self._current.type == TokenType.RPAREN:
                depth -= 1
                parts.append(")")
                previous_type = TokenType.RPAREN
            elif self._current.type in (TokenType.TERM, TokenType.QUOTED_TERM):
                if previous_type in (TokenType.TERM, TokenType.QUOTED_TERM, TokenType.RPAREN):
                    parts.append(" ")
                if pending_not:
                    parts.append("NOT ")
                    pending_not = False
                parts.append(quote_wire_token(self._current.value))
                previous_type = self._current.type
            elif self._current.type == TokenType.OR:
                parts.append(" OR ")
                previous_type = TokenType.OR
            elif self._current.type == TokenType.PLUS:
                # No operator meaning inside a group -- adjacent terms are
                # AND'ed by adjacency already, so '+' is dropped rather than
                # glued onto the next term as a character the AST rejects.
                pass
            elif self._current.type == TokenType.MINUS:
                pending_not = True
            elif self._current.type == TokenType.END:
                return ""  # unbalanced

            if depth > 0:
                self._advance()
            else:
                break

        self._advance()  # skip closing paren
        return "".join(parts)


def parse_search_expression(expression: str) -> SearchExpression:
    """
    Parse a web-style search expression.

    Converts expressions like "+golang -old (tutorial OR guide)" into
    structured format that can be converted to a query string.

    Args:
        expression: Web-style search expression.

    Returns:
        Parsed expression components.

    Raises:
        ValueError: If the expression is empty or malformed.
    """
    if not expression or not expression.strip():
        raise ValueError("Search expression cannot be empty")

    return _Parser(expression).parse()


def has_complex_expression(expr: SearchExpression) -> bool:
    """
    Check whether ``expr`` has OR operators or grouping.

    True when ``raw_expression`` is non-empty, or a required/excluded term
    is itself an already-formatted parenthesized sub-expression.
    """
    if expr.raw_expression:
        return True
    return any(_is_paren_subexpression(t) for t in expr.required_terms) or any(
        _is_paren_subexpression(t) for t in expr.excluded_terms
    )


def _emit_term(term: str) -> str:
    return term if _is_paren_subexpression(term) else quote_wire_token(term)


def to_query_string(expr: SearchExpression) -> str:
    """
    Convert a parsed search expression to a query string.

    Generates a boolean query string: required terms joined with ``AND``,
    each excluded term as ``NOT <term>``, and any OR/grouped sub-expression
    wrapped in parentheses -- all AND-joined together.

    Args:
        expr: Parsed search expression.

    Returns:
        Query string compatible with the server's boolean query parser.
    """
    parts: List[str] = []

    if expr.required_terms:
        parts.append(" AND ".join(_emit_term(t) for t in expr.required_terms))

    for term in expr.excluded_terms:
        parts.append(f"NOT {_emit_term(term)}")

    if expr.raw_expression:
        parts.append(f"({expr.raw_expression})")

    return " AND ".join(parts)


def convert_search_expression(expression: str) -> str:
    """
    Convert a search expression directly to a query string.

    Convenience function combining :func:`parse_search_expression` and
    :func:`to_query_string` in one call.

    Examples:
    - `+golang tutorial` -> `golang AND tutorial`
    - `+golang -old` -> `golang AND NOT old`
    - `python OR ruby` -> `(python OR ruby)`
    - `+golang +(tutorial OR guide)` -> `golang AND (tutorial OR guide)`

    Args:
        expression: Web-style search expression.

    Returns:
        Query string compatible with the server's boolean query parser.

    Raises:
        ValueError: If the expression is empty or malformed.
    """
    return to_query_string(parse_search_expression(expression))


def simplify_search_expression(expression: str) -> SimplifiedExpression:
    """
    Simplify a search expression to basic AND/NOT term lists.

    For clients that don't support the full boolean query syntax, this
    extracts simple term lists. An OR or parenthesized sub-expression has no
    lossless representation as ``main_term``/``and_terms``/``not_terms`` --
    every consumer of ``main_term`` re-applies wire quoting to it, which
    would wrap e.g. ``(python OR ruby)`` as one opaque literal-phrase term
    instead of parsing it as boolean OR -- so it is rejected rather than
    silently changing the expression's meaning.

    Args:
        expression: Web-style search expression.

    Returns:
        Simplified expression with ``main_term``, ``and_terms`` and
        ``not_terms``.

    Raises:
        ValueError: If the expression is empty, malformed, has no required
            terms, or has an OR/parenthesized sub-expression.
    """
    expr = parse_search_expression(expression)

    if has_complex_expression(expr):
        raise ValueError(
            "Expression cannot be represented by the simplified client API"
        )
    if not expr.required_terms:
        raise ValueError("Search expression must have at least one positive term")

    return SimplifiedExpression(
        main_term=expr.required_terms[0],
        and_terms=list(expr.required_terms[1:]),
        not_terms=list(expr.excluded_terms),
    )
