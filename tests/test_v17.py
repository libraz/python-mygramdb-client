"""
Tests for MygramDB v1.7 protocol features:
- Database-qualified table identity (``database.table``)
- ``search_raw`` / ``search_with_highlights``
- ``set_variable`` / ``show_variables``
- ``sync`` / ``sync_status`` / ``sync_stop``
- DUMP filepath quoting
- SYNC_STATUS response framing
"""
import asyncio

import pytest

from mygramdb_client import (
    MygramClient,
    SearchOptions,
    SearchRawOptions,
    parse_table_identity,
    qualify_table_identity,
)
from mygramdb_client.command_utils import (
    escape_query_string,
    quote_command_argument,
)
from mygramdb_client.errors import InputValidationError, ProtocolError


def _run_capturing(coro_factory, response="OK RESULTS 0"):
    """
    Drive a client coroutine while capturing the raw command sent.

    ``response`` may be a string (returned for every call) or a callable taking
    the command and returning the canned response.

    Returns a tuple ``(commands, result)`` where ``commands`` is the list of
    captured command strings and ``result`` is the coroutine's return value.
    """
    client = MygramClient()
    commands = []

    async def capture(command):
        commands.append(command)
        if callable(response):
            return response(command)
        return response

    client._connected = True
    client.send_command = capture  # type: ignore[assignment]

    result = asyncio.run(coro_factory(client))
    return commands, result


# ---------------------------------------------------------------------------
# Quoting / identity helpers (C++ parity)
# ---------------------------------------------------------------------------


class TestEscapeQueryString:
    """escape_query_string mirrors the C++ EscapeQueryString."""

    def test_empty_returns_explicit_empty_token(self):
        assert escape_query_string("") == '""'

    def test_single_tokens_pass_through(self):
        assert escape_query_string("hello") == "hello"
        assert escape_query_string("機械学習") == "機械学習"

    def test_quotes_whitespace(self):
        assert escape_query_string("machine learning") == '"machine learning"'

    def test_escapes_embedded_quotes_and_backslashes(self):
        assert escape_query_string('say "hi"') == '"say \\"hi\\""'
        assert escape_query_string("a\\b c") == '"a\\\\b c"'

    def test_quotes_single_quote_without_space(self):
        assert escape_query_string("o'brien") == "\"o'brien\""

    def test_lone_backslash_not_quoted(self):
        # Matches C++ EscapeQueryString (a lone backslash does not force quoting).
        assert escape_query_string("a\\b") == "a\\b"


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


# ---------------------------------------------------------------------------
# Response framing
# ---------------------------------------------------------------------------


class TestSyncStatusFraming:
    """_is_response_complete treats OK SYNC_STATUS as END-terminated."""

    def test_incomplete_without_end_marker(self):
        client = MygramClient()
        assert not client._is_response_complete("OK SYNC_STATUS\r\n")
        assert not client._is_response_complete(
            "OK SYNC_STATUS\r\nstatus=IDLE\r\n"
        )

    def test_complete_with_end_marker(self):
        client = MygramClient()
        assert client._is_response_complete(
            "OK SYNC_STATUS\r\nstatus=IDLE\r\nEND\r\n"
        )

    def test_complete_with_trailing_blank_line_after_end(self):
        # The server appends a trailing blank line after END for SYNC_STATUS.
        client = MygramClient()
        assert client._is_response_complete(
            'OK SYNC_STATUS\r\nstatus=IDLE message="x"\r\nEND\r\n\r\n'
        )


# ---------------------------------------------------------------------------
# Database-qualified identity pass-through
# ---------------------------------------------------------------------------


class TestDatabaseQualifiedIdentity:
    def test_search_passes_qualified_identity(self):
        commands, _ = _run_capturing(
            lambda c: c.search("app_db.articles", "hello")
        )
        assert "SEARCH app_db.articles hello" in commands[0]

    def test_quotes_multiword_and_not_filter(self):
        commands, _ = _run_capturing(
            lambda c: c.search(
                "articles", "hello",
                SearchOptions(
                    and_terms=["machine learning"],
                    not_terms=["old stuff"],
                    filters={"status": "in review"},
                ),
            )
        )
        cmd = commands[0]
        assert 'AND "machine learning"' in cmd
        assert 'NOT "old stuff"' in cmd
        assert 'FILTER status = "in review"' in cmd

    def test_count_get_facet_pass_qualified_identity(self):
        def respond(command):
            if command.startswith("COUNT"):
                return "OK COUNT 0"
            if command.startswith("GET"):
                return "OK DOC pk1"
            return "OK FACET 0"

        commands, _ = _run_capturing(
            lambda c: c.count("app_db.articles", "x"), response=respond
        )
        assert "COUNT app_db.articles x" in commands[0]

        commands, _ = _run_capturing(
            lambda c: c.get("app_db.articles", "pk1"), response=respond
        )
        assert "GET app_db.articles pk1" in commands[0]

        commands, _ = _run_capturing(
            lambda c: c.facet("app_db.articles", "category"), response=respond
        )
        assert "FACET app_db.articles category" in commands[0]


class TestSearchWithHighlights:
    def test_enables_highlight_clause(self):
        commands, result = _run_capturing(
            lambda c: c.search_with_highlights("articles", "hello"),
            response="OK RESULTS 1\npk1\t<em>hello</em>\n",
        )
        assert "HIGHLIGHT" in commands[0]
        assert result.results[0].primary_key == "pk1"
        assert result.results[0].snippet == "<em>hello</em>"


# ---------------------------------------------------------------------------
# search_raw (boolean expressions)
# ---------------------------------------------------------------------------


class TestSearchRaw:
    def test_quotes_boolean_expression_as_single_token(self):
        commands, _ = _run_capturing(
            lambda c: c.search_raw(
                "articles", "python OR (ruby AND rails)", SearchRawOptions(limit=50)
            )
        )
        cmd = commands[0]
        assert 'SEARCH articles "python OR (ruby AND rails)"' in cmd
        assert cmd.rstrip().endswith("LIMIT 50")

    def test_emits_bare_offset_when_only_offset_set(self):
        commands, _ = _run_capturing(
            lambda c: c.search_raw("articles", "a OR b", SearchRawOptions(offset=20))
        )
        assert commands[0].rstrip().endswith("OFFSET 20")

    def test_rejects_empty_raw_query(self):
        with pytest.raises(InputValidationError):
            asyncio.run(_async_search_raw_empty())

    def test_with_highlights_appends_clause_and_parses_snippet(self):
        commands, result = _run_capturing(
            lambda c: c.search_raw_with_highlights("articles", "a OR b"),
            response="OK RESULTS 1\npk1\tthe <em>a</em> snippet\n",
        )
        assert "HIGHLIGHT" in commands[0]
        assert result.results[0].primary_key == "pk1"
        assert result.results[0].snippet == "the <em>a</em> snippet"


async def _async_search_raw_empty():
    client = MygramClient()
    client._connected = True

    async def capture(command):  # pragma: no cover - must not be reached
        raise AssertionError("send_command should not be called")

    client.send_command = capture  # type: ignore[assignment]
    await client.search_raw("articles", "")


# ---------------------------------------------------------------------------
# SET / SHOW VARIABLES
# ---------------------------------------------------------------------------


class TestSetShowVariables:
    def test_set_variable_emits_set_and_accepts_plus_ok(self):
        commands, _ = _run_capturing(
            lambda c: c.set_variable("logging.level", "info"),
            response="+OK Variable 'logging.level' set to 'info'",
        )
        assert commands[0] == "SET logging.level = info"

    def test_set_variable_quotes_spaced_value(self):
        commands, _ = _run_capturing(
            lambda c: c.set_variable("logging.format", "json pretty"),
            response="+OK done",
        )
        assert commands[0] == 'SET logging.format = "json pretty"'

    def test_set_variable_rejects_empty_name(self):
        with pytest.raises(InputValidationError):
            asyncio.run(_async_set_variable_empty())

    def test_show_variables_no_pattern(self):
        commands, _ = _run_capturing(
            lambda c: c.show_variables(), response="+OK 0 rows"
        )
        assert commands[0] == "SHOW VARIABLES"

    def test_show_variables_like_quoted_pattern(self):
        commands, _ = _run_capturing(
            lambda c: c.show_variables("logging%"), response="+OK 0 rows"
        )
        assert commands[0] == "SHOW VARIABLES LIKE logging%"


async def _async_set_variable_empty():
    client = MygramClient()
    client._connected = True

    async def capture(command):  # pragma: no cover - must not be reached
        raise AssertionError("send_command should not be called")

    client.send_command = capture  # type: ignore[assignment]
    await client.set_variable("", "v")


# ---------------------------------------------------------------------------
# SYNC family
# ---------------------------------------------------------------------------


class TestSyncFamily:
    def test_sync_emits_command_and_returns_ack(self):
        commands, result = _run_capturing(
            lambda c: c.sync("app_db.articles"),
            response="OK SYNC STARTED table=app_db.articles job_id=1",
        )
        assert commands[0] == "SYNC app_db.articles"
        assert "SYNC STARTED" in result

    def test_sync_status_round_trip(self):
        commands, result = _run_capturing(
            lambda c: c.sync_status(),
            response="OK SYNC_STATUS\ntable=users status=IN_PROGRESS\nEND",
        )
        assert commands[0] == "SYNC STATUS"
        assert "table=users" in result
        assert "IN_PROGRESS" in result

    def test_sync_stop_bare_when_no_table(self):
        commands, _ = _run_capturing(
            lambda c: c.sync_stop(), response="OK SYNC STOPPED"
        )
        assert commands[0] == "SYNC STOP"

    def test_sync_stop_named_table(self):
        commands, _ = _run_capturing(
            lambda c: c.sync_stop("articles"), response="OK SYNC STOPPED table=articles"
        )
        assert commands[0] == "SYNC STOP articles"

    def test_sync_surfaces_server_error_as_protocol_error(self):
        # send_command raises ServerError on "ERROR ..."; here we simulate the
        # non-OK acknowledgement path that sync() guards against.
        with pytest.raises(ProtocolError):
            asyncio.run(_async_sync_non_ok())


async def _async_sync_non_ok():
    client = MygramClient()
    client._connected = True

    async def capture(command):
        return "SOMETHING ELSE"

    client.send_command = capture  # type: ignore[assignment]
    await client.sync("articles")


# ---------------------------------------------------------------------------
# DUMP filepath quoting
# ---------------------------------------------------------------------------


class TestDumpFilepathQuoting:
    def test_dump_save_quotes_spaced_filepath(self):
        commands, _ = _run_capturing(
            lambda c: c.dump_save("/var/dumps/my dump.bin"),
            response="OK DUMP_SAVED /var/dumps/my dump.bin",
        )
        assert commands[0] == 'DUMP SAVE "/var/dumps/my dump.bin"'

    def test_dump_save_simple_filepath_unquoted(self):
        commands, _ = _run_capturing(
            lambda c: c.dump_save("/tmp/d.bin"),
            response="OK DUMP_SAVED /tmp/d.bin",
        )
        assert commands[0] == "DUMP SAVE /tmp/d.bin"

    def test_dump_verify_quotes_spaced_filepath(self):
        commands, _ = _run_capturing(
            lambda c: c.dump_verify("/var/my dump.bin"),
            response="OK DUMP_VERIFIED",
        )
        assert commands[0] == 'DUMP VERIFY "/var/my dump.bin"'
