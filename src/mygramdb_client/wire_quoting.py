"""
Shared quote/escape decision for every string reaching the wire.

One predicate (:func:`needs_wire_quoting`) and one encoder
(:func:`quote_wire_token`) back every string this client turns into
wire-protocol text: search terms, filter values, AND/NOT terms, highlight
tags, primary keys and command arguments. Quoting defeats the server's
clause-keyword and AND/OR/NOT recognition (spec/tcp-commands.md §2: "the
quoted flag suppresses clause-keyword recognition"), so a bare token that
happens to collide with a reserved word must go through this same decision
everywhere it can reach the wire, or the collision reappears at whichever
call site skipped it. :func:`parse_wire_token` is the matching decoder for
the other direction: reading a quoted/escaped token back out of a response
(primary keys, header fields). Mirrors the C++ client's
``src/client/wire_quoting.h``.
"""
from typing import List, Optional, Tuple

# Reserved clause keywords, recognized case-insensitively by both the
# top-level command clause scanner and the boolean sub-expression tokenizer.
# A term equal to one of these must be quoted, or it opens a clause instead
# of matching as text.
RESERVED_KEYWORDS = frozenset({
    "AND", "OR", "NOT", "FILTER", "SORT", "LIMIT", "OFFSET",
    "HIGHLIGHT", "FUZZY", "FACET", "ORDER",
})

# ASCII whitespace the server's tokenizer splits on outside quotes -- the C
# isspace() set (space, tab, LF, VT, FF, CR), not Python's broader str.isspace().
_ASCII_WHITESPACE = frozenset(" \t\n\v\f\r")

# Non-ASCII whitespace code points the server's tokenizer also splits on
# outside quotes (spec/tcp-commands.md §2): U+00A0, U+1680, U+2000-U+200B,
# U+2028, U+2029, U+202F, U+205F, U+3000.
_UNICODE_WHITESPACE = frozenset(
    {chr(code) for code in (0x00A0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000)}
    | {chr(code) for code in range(0x2000, 0x200C)}
)

_QUOTE_TRIGGER_CHARS = frozenset({'"', "'", "\\", "(", ")"})

_ESCAPE_MAP = {"\\": "\\\\", '"': '\\"', "\r": "\\r", "\n": "\\n", "\t": "\\t"}


def is_wire_whitespace(ch: str) -> bool:
    """Check whether ``ch`` is ASCII or Unicode whitespace per the server's tokenizer."""
    return ch in _ASCII_WHITESPACE or ch in _UNICODE_WHITESPACE


def _is_control_char(ch: str) -> bool:
    """Check whether ``ch`` is an ASCII control character (0x00-0x1F or 0x7F)."""
    code = ord(ch)
    return code < 0x20 or code == 0x7F


def needs_wire_quoting(value: str) -> bool:
    """
    Check whether ``value`` must be quoted to survive the wire tokenizer intact.

    True when ``value`` is empty, is a reserved keyword (case-insensitive),
    or contains a byte the server's tokenizer treats specially outside
    quotes: ASCII or Unicode whitespace, a control character, a quote
    (``"`` or ``'``), a backslash, or a parenthesis.
    """
    if value == "":
        return True
    if value.upper() in RESERVED_KEYWORDS:
        return True
    for ch in value:
        if ch in _QUOTE_TRIGGER_CHARS or is_wire_whitespace(ch) or _is_control_char(ch):
            return True
    return False


def quote_wire_token(value: str) -> str:
    """
    Quote and escape ``value`` for the wire protocol, only if needed.

    Returns ``value`` unchanged when :func:`needs_wire_quoting` is false.
    Otherwise wraps it in double quotes, backslash-escaping ``\\`` and
    ``"``, the common control characters as ``\\r``/``\\n``/``\\t``, and any
    other control byte as ``\\xHH`` -- reversible by the server's own
    quoted-string reader (spec/tcp-commands.md §2) and by
    :func:`parse_wire_token` on responses the client reads back.
    """
    if not needs_wire_quoting(value):
        return value

    out = ['"']
    for ch in value:
        mapped = _ESCAPE_MAP.get(ch)
        if mapped is not None:
            out.append(mapped)
        elif _is_control_char(ch):
            out.append(f"\\x{ord(ch):02X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _hex_digit_value(ch: str) -> int:
    """Decode one hex digit; -1 if ``ch`` is not [0-9a-fA-F]."""
    if "0" <= ch <= "9":
        return ord(ch) - ord("0")
    if "a" <= ch <= "f":
        return 10 + (ord(ch) - ord("a"))
    if "A" <= ch <= "F":
        return 10 + (ord(ch) - ord("A"))
    return -1


def parse_wire_token(text: str, pos: int) -> Optional[Tuple[str, int]]:
    """
    Read one whitespace-delimited or quoted token, inverse of :func:`quote_wire_token`.

    Skips leading ASCII whitespace, then reads either a bare token (up to
    the next ASCII whitespace) or, if the token opens with ``"``, a quoted
    token -- unescaping ``\\\\``, ``\\"``, ``\\r``, ``\\n``, ``\\t`` and
    ``\\xHH`` back to their literal characters. Used to read a response the
    server quoted per spec/tcp-commands.md §11.1 (primary keys, header
    fields) back into the value :func:`quote_wire_token` would have
    produced from it.

    Args:
        text: Text to read a token from.
        pos: Offset to start reading at.

    Returns:
        ``(value, new_pos)`` on success, or ``None`` on an unterminated
        quote, a truncated ``\\x`` escape, or nothing left to read.
    """
    length = len(text)
    while pos < length and text[pos] in _ASCII_WHITESPACE:
        pos += 1
    if pos >= length:
        return None

    if text[pos] != '"':
        start = pos
        while pos < length and text[pos] not in _ASCII_WHITESPACE:
            pos += 1
        return text[start:pos], pos

    pos += 1
    chars: List[str] = []
    while pos < length:
        ch = text[pos]
        pos += 1
        if ch == '"':
            return "".join(chars), pos
        if ch != "\\":
            chars.append(ch)
            continue
        if pos >= length:
            return None
        escaped = text[pos]
        pos += 1
        if escaped == "n":
            chars.append("\n")
        elif escaped == "r":
            chars.append("\r")
        elif escaped == "t":
            chars.append("\t")
        elif escaped in ("\\", '"'):
            chars.append(escaped)
        elif escaped == "x":
            if pos + 1 >= length:
                return None
            high = _hex_digit_value(text[pos])
            low = _hex_digit_value(text[pos + 1])
            if high < 0 or low < 0:
                return None
            chars.append(chr((high << 4) | low))
            pos += 2
        else:
            chars.append(escaped)

    return None
