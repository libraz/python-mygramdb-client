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
- `OR` - Logical OR between terms (implicit AND binds tighter)

Examples:
- `golang tutorial` -> `golang AND tutorial` (implicit AND)
- `"machine learning" tutorial` -> `"machine learning" AND tutorial`
- `golang -old` -> `golang AND NOT old`
- `python OR ruby` -> `(python OR ruby)`
- `a OR b c` -> `(a OR b c)` (a top-level OR makes the whole expression one group)
- `golang +(tutorial OR guide)` -> `golang AND (tutorial OR guide)`
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple

from .types import SimplifiedExpression
from .wire_quoting import is_wire_whitespace, quote_wire_token


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
    raw_expression: str = ""
    """Formatted AST-syntax text for a bare OR/grouped sub-expression."""
    required_is_group: List[bool] = field(default_factory=list)
    """Parallel to :attr:`required_terms`: the entry is a formatted ``(...)`` group."""
    excluded_is_group: List[bool] = field(default_factory=list)
    """Parallel to :attr:`excluded_terms`: the entry is a formatted ``(...)`` group."""


_OR_SPELLINGS = frozenset({"OR", "Or", "oR", "or"})


def _is_group_entry(is_group: List[bool], index: int) -> bool:
    """
    Check whether entry ``index`` of a term list is a formatted group.

    The flags run parallel to the term list; a missing flag means plain text.
    A group is identified structurally, never by its text, so a quoted phrase
    such as ``"(a b)"`` stays an ordinary term that still gets quoted.
    """
    return index < len(is_group) and is_group[index]


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

        # OR operator: a whole token, delimited by whitespace, a parenthesis
        # or a double quote on both sides, so "OR-tools" and "OR回路" stay terms.
        if (
            self.input[self.pos:self.pos + 2] in _OR_SPELLINGS
            and self._is_operator_boundary_before(self.pos)
            and self._is_operator_boundary_after(self.pos + 2)
        ):
            self.pos += 2
            return Token(TokenType.OR, "OR")

        return Token(TokenType.TERM, self._read_term())

    def _is_operator_boundary_after(self, pos: int) -> bool:
        """Whether an operator word may end at ``pos``."""
        if pos >= len(self.input):
            return True
        ch = self.input[pos]
        return is_wire_whitespace(ch) or ch in '()"'

    def _is_operator_boundary_before(self, pos: int) -> bool:
        """Whether an operator word may start at ``pos``."""
        if pos == 0:
            return True
        ch = self.input[pos - 1]
        return is_wire_whitespace(ch) or ch in '()"'

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

        if self._has_top_level_or():
            expr.raw_expression = self._capture_top_level_or_group()
            return expr

        while self._current.type != TokenType.END:
            if self._current.type == TokenType.PLUS:
                self._advance()
                operand = self._parse_prefixed_term()
                if operand is None:
                    raise ValueError("Expected term after '+'")
                expr.required_terms.append(operand[0])
                expr.required_is_group.append(operand[1])
            elif self._current.type == TokenType.MINUS:
                self._advance()
                operand = self._parse_prefixed_term()
                if operand is None:
                    raise ValueError("Expected term after '-'")
                expr.excluded_terms.append(operand[0])
                expr.excluded_is_group.append(operand[1])
            elif self._current.type == TokenType.LPAREN:
                paren_expr = self._capture_paren_expression()
                if not paren_expr:
                    raise ValueError("Unbalanced parentheses")
                if expr.raw_expression:
                    expr.raw_expression += " "
                expr.raw_expression += paren_expr
            elif self._current.type in (TokenType.TERM, TokenType.QUOTED_TERM):
                # Stored as plain text regardless of whether it was quoted --
                # to_query_string/simplify_search_expression each apply the
                # shared wire-quoting decision exactly once, at whichever
                # destination the term is serialized.
                expr.required_terms.append(self._current.value)
                expr.required_is_group.append(False)
                self._advance()
            elif self._current.type == TokenType.OR:
                raise ValueError("Unexpected 'OR' operator")
            elif self._current.type == TokenType.RPAREN:
                raise ValueError("Unexpected ')'")
            else:
                self._advance()

        return expr

    def _parse_prefixed_term(self) -> Optional[Tuple[str, bool]]:
        """Operand of a unary +/-: ``(text, is_group)``, or ``None`` if absent."""
        if self._current.type == TokenType.LPAREN:
            expr = self._capture_paren_expression()
            return (expr, True) if expr else None
        if self._current.type in (TokenType.TERM, TokenType.QUOTED_TERM):
            term = self._current.value
            self._advance()
            return (term, False)
        return None

    def _has_top_level_or(self) -> bool:
        """Whether an OR operator appears outside every parenthesized group."""
        saved_pos = self._tokenizer.get_position()
        saved_current = self._current

        found = False
        depth = 0
        while self._current.type != TokenType.END and not found:
            if self._current.type == TokenType.LPAREN:
                depth += 1
            elif self._current.type == TokenType.RPAREN:
                depth -= 1
            elif self._current.type == TokenType.OR and depth <= 0:
                found = True
            self._advance()

        self._tokenizer.set_position(saved_pos)
        self._current = saved_current
        return found

    def _capture_top_level_or_group(self) -> str:
        """
        Capture the whole expression as one group when it has a top-level OR.

        Implicit AND binds tighter than OR, so ``a OR b c`` is ``a OR (b c)``,
        exactly what the parenthesized form ``(a OR b c)`` means to the server
        grammar.
        """
        parts: List[str] = []
        previous_type = TokenType.END
        pending_not = False

        while self._current.type != TokenType.END:
            current = self._current.type
            if current == TokenType.OR:
                if previous_type in (TokenType.END, TokenType.OR):
                    raise ValueError("Unexpected 'OR' operator")
                pending_not = False
                parts.append(" OR ")
                previous_type = TokenType.OR
                self._advance()
            elif current in (TokenType.PLUS, TokenType.MINUS):
                if previous_type in (TokenType.END, TokenType.OR):
                    raise ValueError("Expected term next to 'OR'")
                pending_not = current == TokenType.MINUS
                self._advance()
            elif current == TokenType.RPAREN:
                raise ValueError("Unexpected ')'")
            else:
                # A term, quoted term or parenthesized group.
                is_group = current == TokenType.LPAREN
                if is_group:
                    operand = self._capture_paren_expression()
                    if not operand:
                        raise ValueError(
                            "Unbalanced parentheses after 'OR'"
                            if previous_type == TokenType.OR
                            else "Unbalanced parentheses"
                        )
                else:
                    operand = quote_wire_token(self._current.value)
                    self._advance()
                if previous_type in (TokenType.TERM, TokenType.QUOTED_TERM, TokenType.RPAREN):
                    parts.append(" ")
                if pending_not:
                    parts.append("NOT ")
                    pending_not = False
                parts.append(operand)
                previous_type = TokenType.RPAREN if is_group else current

        if previous_type == TokenType.OR:
            raise ValueError("Expected term after 'OR'")
        return "".join(parts)

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
        # only understands the literal word NOT. Defer emission to the very
        # next token: a term or a nested group takes the NOT, anything else
        # drops it, so it never leaks onto a later term.
        pending_not = False

        while True:
            if self._current.type == TokenType.LPAREN:
                if previous_type in (TokenType.TERM, TokenType.QUOTED_TERM, TokenType.RPAREN):
                    parts.append(" ")
                if pending_not:
                    parts.append("NOT ")
                    pending_not = False
                depth += 1
                parts.append("(")
                previous_type = TokenType.LPAREN
            elif self._current.type == TokenType.RPAREN:
                pending_not = False
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
                pending_not = False
                parts.append(" OR ")
                previous_type = TokenType.OR
            elif self._current.type == TokenType.PLUS:
                # No operator meaning inside a group -- adjacent terms are
                # AND'ed by adjacency already, so '+' is dropped rather than
                # glued onto the next term as a character the AST rejects.
                pending_not = False
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
    is flagged as an already-formatted parenthesized group.
    """
    return bool(expr.raw_expression) or any(expr.required_is_group) or any(
        expr.excluded_is_group
    )


def _emit_term(term: str, is_group: bool) -> str:
    return term if is_group else quote_wire_token(term)


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
        parts.append(
            " AND ".join(
                _emit_term(t, _is_group_entry(expr.required_is_group, i))
                for i, t in enumerate(expr.required_terms)
            )
        )

    for i, term in enumerate(expr.excluded_terms):
        parts.append(f"NOT {_emit_term(term, _is_group_entry(expr.excluded_is_group, i))}")

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
