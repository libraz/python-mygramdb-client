"""Command construction for the administrative verbs: SET, SHOW, SYNC, DUMP.

These share one concern — a free-form argument (a variable value, a filepath)
has to survive tokenization — so they are asserted together.
"""
import asyncio

import pytest

from mygramdb_client.errors import InputValidationError, ProtocolError

from .command_capture import run_capturing, unreachable_client


class TestSetShowVariables:
    def test_set_variable_emits_set_and_accepts_plus_ok(self):
        commands, _ = run_capturing(
            lambda c: c.set_variable("logging.level", "info"),
            response="+OK Variable 'logging.level' set to 'info'",
        )
        assert commands[0] == "SET logging.level = info"

    def test_set_variable_quotes_spaced_value(self):
        commands, _ = run_capturing(
            lambda c: c.set_variable("logging.format", "json pretty"),
            response="+OK done",
        )
        assert commands[0] == 'SET logging.format = "json pretty"'

    def test_set_variable_rejects_empty_name(self):
        async def issue():
            await unreachable_client().set_variable("", "v")

        with pytest.raises(InputValidationError):
            asyncio.run(issue())

    def test_show_variables_no_pattern(self):
        commands, _ = run_capturing(
            lambda c: c.show_variables(), response="+OK 0 rows"
        )
        assert commands[0] == "SHOW VARIABLES"

    def test_show_variables_like_quoted_pattern(self):
        commands, _ = run_capturing(
            lambda c: c.show_variables("logging%"), response="+OK 0 rows"
        )
        assert commands[0] == "SHOW VARIABLES LIKE logging%"


class TestSyncFamily:
    def test_sync_emits_command_and_returns_ack(self):
        commands, result = run_capturing(
            lambda c: c.sync("app_db.articles"),
            response="OK SYNC STARTED table=app_db.articles job_id=1",
        )
        assert commands[0] == "SYNC app_db.articles"
        assert "SYNC STARTED" in result

    def test_sync_status_round_trip(self):
        commands, result = run_capturing(
            lambda c: c.sync_status(),
            response="OK SYNC_STATUS\ntable=users status=IN_PROGRESS\nEND",
        )
        assert commands[0] == "SYNC STATUS"
        assert "table=users" in result
        assert "IN_PROGRESS" in result

    def test_sync_stop_bare_when_no_table(self):
        commands, _ = run_capturing(
            lambda c: c.sync_stop(), response="OK SYNC STOPPED"
        )
        assert commands[0] == "SYNC STOP"

    def test_sync_stop_named_table(self):
        commands, _ = run_capturing(
            lambda c: c.sync_stop("articles"),
            response="OK SYNC STOPPED table=articles",
        )
        assert commands[0] == "SYNC STOP articles"

    def test_sync_surfaces_a_non_ok_acknowledgement_as_protocol_error(self):
        # send_command raises ServerError on "ERROR ..."; this covers the
        # other path — an acknowledgement sync() does not recognize.
        with pytest.raises(ProtocolError):
            run_capturing(
                lambda c: c.sync("articles"), response="SOMETHING ELSE"
            )


class TestDumpFilepathQuoting:
    def test_dump_save_quotes_spaced_filepath(self):
        commands, _ = run_capturing(
            lambda c: c.dump_save("/var/dumps/my dump.bin"),
            response="OK DUMP_SAVED /var/dumps/my dump.bin",
        )
        assert commands[0] == 'DUMP SAVE "/var/dumps/my dump.bin"'

    def test_dump_save_simple_filepath_unquoted(self):
        commands, _ = run_capturing(
            lambda c: c.dump_save("/tmp/d.bin"),
            response="OK DUMP_SAVED /tmp/d.bin",
        )
        assert commands[0] == "DUMP SAVE /tmp/d.bin"

    def test_dump_verify_quotes_spaced_filepath(self):
        commands, _ = run_capturing(
            lambda c: c.dump_verify("/var/my dump.bin"),
            response="OK DUMP_VERIFIED",
        )
        assert commands[0] == 'DUMP VERIFY "/var/my dump.bin"'
