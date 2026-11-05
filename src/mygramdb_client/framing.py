"""
Response-frame completion detection.

The TCP protocol has no length prefix and several replies carry blank lines
inside their bodies, so whether the bytes received so far form the whole frame
depends on which command was sent. :func:`begin_response_frame` records that
context once per request (command verb, a SEARCH ``HIGHLIGHT`` clause, the
connection's DEBUG flag); :func:`is_response_complete` then walks the reply
line by line and stops exactly at the frame's last CRLF. The one exception is
the transport CRLF after an ``OK FACET`` reply whose header omits the
distinct-value total: the next frame skips it as a leading blank line.
The grammar follows spec/tcp-commands.md §8, §10 and §12, with the transport
CRLF the server appends to every response body (§1) included. An ``ERROR``
line ends every frame. Mirrors the C++ client's ``src/client/protocol_detection.h``.
"""
import string
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Sequence, Union

from .wire_quoting import is_wire_whitespace

_CRLF = b"\r\n"
_END_LINE = b"END"
_TABLE_BORDER_PREFIX = b"+-"

_ERROR_PREFIX = b"ERROR "
_OK_INFO = b"OK INFO"
_OK_REPLICATION = b"OK REPLICATION"
_OK_CACHE_STATS = b"OK CACHE_STATS"
_OK_DUMP_STATUS = b"OK DUMP_STATUS"
_OK_DUMP_INFO = b"OK DUMP_INFO"
_OK_SYNC_STATUS = b"OK SYNC_STATUS"
_OK_FACET = b"OK FACET"
_OK_FACET_WITH_SPACE = b"OK FACET "
_PLUS_OK = b"+OK"
_OK_RESULTS_WITH_SPACE = b"OK RESULTS "
_OK_COUNT_WITH_SPACE = b"OK COUNT "

#: Reply to ``DEBUG ON`` / ``DEBUG OFF``; the connection's DEBUG flag follows it.
OK_DEBUG_ON = "OK DEBUG_ON"
OK_DEBUG_OFF = "OK DEBUG_OFF"

_NON_EXPRESSION_CLAUSE_KEYWORDS = frozenset(
    {"FILTER", "SORT", "LIMIT", "OFFSET", "HIGHLIGHT", "FUZZY", "FACET"}
)
_FILTER_OPERATORS = (">=", "<=", "!=", "<>", "=", ">", "<")
_SEPARATE_FILTER_OPERANDS = 3
_SEARCH_TEXT_START = 2


@dataclass
class RequestToken:
    """
    One request token as the server tokenizer splits it
    (spec/tcp-commands.md §2.1).

    ``text`` is the raw token without surrounding quotes and with escapes left
    undecoded.
    """

    text: str
    quoted: bool = False


def tokenize_request(command: str) -> List[RequestToken]:
    """
    Split a request line the way the server tokenizer does.

    Splits on ASCII and Unicode whitespace outside quotes; ``"`` and ``'`` open
    a quoted region that a backslash escape cannot close, and opening a quote
    flushes any pending unquoted token. Only token boundaries and the quoted
    flag are recovered; escapes are not decoded.
    """
    tokens: List[RequestToken] = []
    start = -1

    def flush(end: int) -> None:
        nonlocal start
        if start >= 0:
            tokens.append(RequestToken(command[start:end], False))
            start = -1

    pos = 0
    length = len(command)
    while pos < length:
        ch = command[pos]
        if is_wire_whitespace(ch):
            flush(pos)
            pos += 1
            continue
        if ch in "\"'":
            flush(pos)
            pos += 1
            open_pos = pos
            while pos < length and command[pos] != ch:
                pos += 2 if command[pos] == "\\" else 1
            close = min(pos, length)
            tokens.append(RequestToken(command[open_pos:close], True))
            pos = close + 1
            continue
        if start < 0:
            start = pos
        pos += 1
    flush(length)
    return tokens


def _hex_value(ch: str) -> int:
    """Decode one ASCII hex digit; -1 if ``ch`` is not ``[0-9a-fA-F]``."""
    return int(ch, 16) if ch in string.hexdigits else -1


def decode_request_token(token: RequestToken) -> str:
    """
    Decode a request token's escapes the way the server tokenizer does.

    Inside quotes ``\\n``, ``\\t``, ``\\r``, ``\\\\``, ``\\"``, ``\\'`` and
    ``\\xHH`` decode, ``\\x`` without two hex digits is ``x``, and any other
    escaped character stands for itself. An unquoted token is taken verbatim,
    backslashes included.
    """
    text = token.text
    if not token.quoted:
        return text
    out: List[str] = []
    i = 0
    length = len(text)
    while i < length:
        if text[i] != "\\" or i + 1 >= length:
            out.append(text[i])
            i += 1
            continue
        i += 1
        escaped = text[i]
        if escaped == "n":
            out.append("\n")
        elif escaped == "t":
            out.append("\t")
        elif escaped == "r":
            out.append("\r")
        elif escaped == "x":
            high = _hex_value(text[i + 1]) if i + 2 < length else -1
            low = _hex_value(text[i + 2]) if i + 2 < length else -1
            if high >= 0 and low >= 0:
                out.append(chr((high << 4) | low))
                i += 2
            else:
                out.append("x")
        else:
            out.append(escaped)
        i += 1
    return "".join(out)


def _ascii_upper(value: str) -> str:
    """Upper-case ASCII letters only, as the server's keyword comparison does."""
    return "".join(ch.upper() if "a" <= ch <= "z" else ch for ch in value)


def _equals_ignore_case(lhs: str, rhs: str) -> bool:
    """ASCII case-insensitive equality against an upper-case ``rhs``."""
    return _ascii_upper(lhs) == rhs


def _is_non_expression_clause_keyword(token: str) -> bool:
    return _ascii_upper(token) in _NON_EXPRESSION_CLAUSE_KEYWORDS


def _is_clause_keyword(token: str) -> bool:
    return _is_non_expression_clause_keyword(token) or _ascii_upper(token) in ("AND", "OR", "NOT")


def _paren_delta(text: str) -> int:
    return text.count("(") - text.count(")")


def _skip_search_text(tokens: Sequence[RequestToken], start: int) -> int:
    """
    Find where the server ends a SEARCH's search text.

    The text is a Boolean expression when it opens with NOT, or when a
    top-level OR, or a parenthesized group after a top-level AND/NOT, comes
    before the first clause keyword. A Boolean expression ends only at a
    top-level non-expression clause keyword; a flat one also at AND, OR or
    NOT. Quoted tokens are never keywords and their parentheses never count.

    Returns:
        Index of the first token after the search text.
    """
    boolean_expression = (
        start < len(tokens)
        and not tokens[start].quoted
        and _equals_ignore_case(tokens[start].text, "NOT")
    )
    depth = 0
    seen_operator = False
    i = start
    while i < len(tokens) and not boolean_expression:
        token = tokens[i]
        i += 1
        if token.quoted:
            continue
        text = token.text
        if depth == 0 and seen_operator and "(" in text:
            boolean_expression = True
        depth += _paren_delta(text)
        if depth == 0 and (
            _is_non_expression_clause_keyword(text) or _equals_ignore_case(text, "ORDER")
        ):
            break
        if depth == 0 and _equals_ignore_case(text, "OR"):
            boolean_expression = True
        if depth == 0 and (
            _equals_ignore_case(text, "AND") or _equals_ignore_case(text, "NOT")
        ):
            seen_operator = True

    depth = 0
    pos = start
    while pos < len(tokens):
        token = tokens[pos]
        if not token.quoted:
            depth += _paren_delta(token.text)
            if depth == 0 and (
                _is_non_expression_clause_keyword(token.text)
                or (not boolean_expression and _is_clause_keyword(token.text))
            ):
                break
        pos += 1
    return pos


def _starts_with_operator(value: str) -> bool:
    return bool(value) and value[0] in "=<>!"


def _skip_filter_operands(tokens: Sequence[RequestToken], pos: int) -> int:
    """
    Skip the operands of a FILTER clause the way the server consumes them.

    A token holding the operator (``col=value``, or ``col=`` followed by the
    value) is one or two tokens; otherwise the clause takes ``col op value``.

    Args:
        pos: Index just after FILTER.

    Returns:
        Index just after the clause's operands.
    """
    if pos >= len(tokens):
        return pos
    first = decode_request_token(tokens[pos])
    for op in _FILTER_OPERATORS:
        at = first.find(op)
        if at < 0:
            continue
        value = first[at + len(op):]
        if at > 0 and value and not _starts_with_operator(value):
            return pos + 1
        if (
            at > 0
            and not value
            and pos + 1 < len(tokens)
            and not _starts_with_operator(decode_request_token(tokens[pos + 1]))
        ):
            return pos + 2
        break
    return pos + _SEPARATE_FILTER_OPERANDS


def _skip_sort_operands(tokens: Sequence[RequestToken], pos: int) -> int:
    """
    Skip the operands of a SORT clause: ``[BY] col [ASC|DESC]`` or
    ``[BY] ASC|DESC``.

    Args:
        pos: Index just after SORT.

    Returns:
        Index just after the clause's operands.
    """

    def token_is(index: int, word: str) -> bool:
        return index < len(tokens) and _equals_ignore_case(
            decode_request_token(tokens[index]), word
        )

    def is_order(index: int) -> bool:
        return token_is(index, "ASC") or token_is(index, "DESC")

    if token_is(pos, "BY"):
        pos += 1
    if is_order(pos):
        return pos + 1
    pos += 1
    return pos + 1 if is_order(pos) else pos


def _search_requests_highlight(tokens: Sequence[RequestToken]) -> bool:
    """
    Check whether a SEARCH carries a HIGHLIGHT clause.

    After the search text each clause consumes its operands (AND and NOT one
    term, AND NOT two, FILTER and SORT as above, LIMIT and OFFSET one token,
    FUZZY an optional distance), and only an unquoted HIGHLIGHT in clause
    position counts. Requests the server rejects reply with ERROR, which ends
    the frame whatever this returns.
    """

    def keyword_at(index: int, keyword: str) -> bool:
        return (
            index < len(tokens)
            and not tokens[index].quoted
            and _equals_ignore_case(tokens[index].text, keyword)
        )

    pos = _skip_search_text(tokens, _SEARCH_TEXT_START)
    while pos < len(tokens):
        clause = pos
        pos += 1
        if keyword_at(clause, "HIGHLIGHT"):
            return True
        if keyword_at(clause, "AND"):
            pos += 2 if keyword_at(pos, "NOT") else 1
        elif (
            keyword_at(clause, "NOT")
            or keyword_at(clause, "LIMIT")
            or keyword_at(clause, "OFFSET")
        ):
            pos += 1
        elif keyword_at(clause, "FILTER"):
            pos = _skip_filter_operands(tokens, pos)
        elif keyword_at(clause, "SORT"):
            pos = _skip_sort_operands(tokens, pos)
        elif keyword_at(clause, "FUZZY"):
            if pos < len(tokens) and not _is_clause_keyword(decode_request_token(tokens[pos])):
                pos += 1
        else:
            return False
    return False


class FrameCommand(Enum):
    """Commands whose reply grammar cannot be told from the reply's first line alone."""

    OTHER = auto()
    SEARCH = auto()
    """``OK RESULTS`` may carry highlight rows and/or a DEBUG block."""
    COUNT = auto()
    """``OK COUNT`` may carry a DEBUG block."""
    CONFIG_HELP = auto()
    """The ``+OK`` body carries exactly one internal blank line."""


@dataclass
class ResponseFrameState:
    """
    Per-request framing context plus the parse position inside the reply.

    Create one with :func:`begin_response_frame` for every request and pass it
    to each :func:`is_response_complete` call for that request's reply.
    """

    command: FrameCommand = FrameCommand.OTHER
    debug: bool = False
    """The connection had DEBUG ON when the command was sent."""
    highlight: bool = False
    """A SEARCH carried an unquoted HIGHLIGHT clause."""

    line_start: int = 0
    """Offset of the first line not yet consumed."""
    scan_offset: int = 0
    """Where the CRLF search resumes inside an unfinished line."""
    frame_start: int = 0
    """Offset of the status line; blank lines before it are a prior reply's leftover."""
    header_seen: bool = False
    body_line_pending: bool = False
    """The next line is body even if empty (bare ``+OK``)."""
    until_end_line: bool = False
    """Lines are body until one reads exactly ``END``."""
    blank_lines_left: int = 0
    """Empty lines still to come; the last one ends the frame."""


def begin_response_frame(command: str, debug_mode: bool) -> ResponseFrameState:
    """
    Record the framing context of a request before its reply is read.

    Args:
        command: The request line as sent, without its CRLF.
        debug_mode: Whether the connection has DEBUG ON (spec §10.7).
    """
    tokens = tokenize_request(command)
    state = ResponseFrameState(debug=debug_mode)
    if not tokens:
        return state
    verb = tokens[0].text
    if _equals_ignore_case(verb, "SEARCH"):
        state.command = FrameCommand.SEARCH
        state.highlight = _search_requests_highlight(tokens)
    elif _equals_ignore_case(verb, "COUNT"):
        state.command = FrameCommand.COUNT
    elif (
        _equals_ignore_case(verb, "CONFIG")
        and len(tokens) > 1
        and _equals_ignore_case(tokens[1].text, "HELP")
    ):
        state.command = FrameCommand.CONFIG_HELP
    return state


def _consume_response_header(line: bytes, state: ResponseFrameState) -> bool:
    """
    Classify the status line and set up the rest of the frame.

    Returns:
        True when the status line is the whole frame.
    """
    if line.startswith(_ERROR_PREFIX):
        return True
    if (
        line in (_OK_INFO, _OK_REPLICATION, _OK_CACHE_STATS, _OK_DUMP_STATUS)
        or line.startswith(_OK_DUMP_INFO)
    ):
        state.until_end_line = True
    elif line == _OK_SYNC_STATUS:
        # The body already ends in "END\r\n", so the transport CRLF adds a blank line.
        state.until_end_line = True
        state.blank_lines_left = 1
    elif line.startswith(_OK_FACET):
        # Rows, a blank line closing the body, then the transport CRLF. Without
        # the distinct-value total the frame ends at the first blank line; a
        # CRLF after it is skipped as the next reply's leading blank line.
        has_total = line.find(b" ", len(_OK_FACET_WITH_SPACE)) >= 0
        state.blank_lines_left = 2 if has_total else 1
    elif line.startswith(_TABLE_BORDER_PREFIX):
        # Non-empty SHOW VARIABLES: a bare table with no status prefix (spec §10.10).
        state.blank_lines_left = 1
    elif line == _PLUS_OK:
        # CONFIG body: at least one line, which may be empty when CONFIG SHOW
        # renders an empty value.
        state.body_line_pending = True
        state.blank_lines_left = 2 if state.command == FrameCommand.CONFIG_HELP else 1
    elif line.startswith(_PLUS_OK):
        state.blank_lines_left = 1
    elif state.command == FrameCommand.SEARCH and line.startswith(_OK_RESULTS_WITH_SPACE):
        # A highlight header carries only the count; primary keys on it mean a plain reply.
        after_count = line[len(_OK_RESULTS_WITH_SPACE):]
        highlight_rows = state.highlight and not after_count.strip(b"0123456789")
        state.blank_lines_left = (1 if highlight_rows else 0) + (2 if state.debug else 0)
    elif state.command == FrameCommand.COUNT and line.startswith(_OK_COUNT_WITH_SPACE):
        state.blank_lines_left = 2 if state.debug else 0
    return not state.until_end_line and not state.body_line_pending and state.blank_lines_left == 0


def is_response_complete(
    response: Union[bytes, bytearray], state: ResponseFrameState
) -> bool:
    """
    Check whether the accumulated reply bytes are one complete frame.

    Call after every read with all bytes received so far for the request
    ``state`` was begun for; already-consumed lines are not rescanned.

    Args:
        response: Accumulated reply bytes.
        state: Context from :func:`begin_response_frame`, advanced in place.

    Returns:
        True when ``response`` ends exactly at the end of the frame. The
        frame itself starts at ``state.frame_start``.
    """
    while True:
        line_end = response.find(_CRLF, max(state.line_start, state.scan_offset))
        if line_end < 0:
            state.scan_offset = len(response) - 1 if response else 0
            return False
        line = bytes(response[state.line_start:line_end])
        state.line_start = line_end + len(_CRLF)

        if not state.header_seen:
            # No reply starts with a blank line, so one here is left over from
            # the previous reply.
            if not line:
                state.frame_start = state.line_start
                continue
            state.header_seen = True
            if _consume_response_header(line, state):
                return True
            continue
        if state.body_line_pending:
            state.body_line_pending = False
            continue
        if state.until_end_line:
            if line == _END_LINE:
                state.until_end_line = False
                if state.blank_lines_left == 0:
                    return True
            continue
        if not line:
            state.blank_lines_left -= 1
            if state.blank_lines_left == 0:
                return True
