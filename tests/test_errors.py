"""The error surface: exception hierarchy, and decoding of server ERROR frames.

An ``ERROR`` frame is where the server's taxonomy crosses into the client's,
so the decoding tests live next to the exception hierarchy they produce.
"""
import builtins

import pytest

from mygramdb_client import (
    AuthenticationError,
    ClientConfig,
    ConnectionError,
    ErrorCode,
    MygramClient,
    MygramError,
    RetryPolicy,
    ServerBusyError,
    ServerError,
    ServerNotReadyError,
    TimeoutError,
)
from mygramdb_client.errors import (
    PoolExhaustedError,
    PoolTimeoutError,
    parse_error_frame,
)

from .fake_server import FakeMygramServer


class TestBuiltinCompatibility:
    def test_timeout_error_is_builtin_and_mygram(self):
        err = TimeoutError("timed out")
        assert isinstance(err, builtins.TimeoutError)
        assert isinstance(err, MygramError)
        assert isinstance(err, OSError)  # builtin TimeoutError derives from OSError
        assert str(err) == "timed out"
        assert err.code == "TIMEOUT_ERROR"

    def test_connection_error_is_builtin_and_mygram(self):
        err = ConnectionError("connection lost")
        assert isinstance(err, builtins.ConnectionError)
        assert isinstance(err, MygramError)
        assert str(err) == "connection lost"
        assert err.code == "CONNECTION_ERROR"

    def test_catchable_as_builtin(self):
        # A caller using the builtin name (not the library import) still catches it.
        try:
            raise TimeoutError("x")
        except builtins.TimeoutError as caught:
            assert isinstance(caught, MygramError)
        else:  # pragma: no cover
            raise AssertionError("not caught as builtin TimeoutError")

    def test_pool_errors_preserve_hierarchy(self):
        assert isinstance(PoolTimeoutError("p"), TimeoutError)
        assert isinstance(PoolTimeoutError("p"), builtins.TimeoutError)
        assert isinstance(PoolExhaustedError("p"), MygramError)
        assert PoolTimeoutError("p").code == "POOL_TIMEOUT_ERROR"


class TestErrorFrameDecoding:
    """Numeric codes on ERROR frames, decoded into typed exceptions (v1.10+)."""

    def test_coded_frame_yields_code_and_message(self):
        error = parse_error_frame("ERROR 4007 Table not found: articles")

        assert isinstance(error, ServerError)
        assert error.error_code == ErrorCode.TABLE_NOT_FOUND
        assert error.message == "Table not found: articles"

    def test_untyped_frame_keeps_whole_payload_as_message(self):
        error = parse_error_frame("ERROR Table not found: articles")

        assert error.error_code is None
        assert error.message == "Table not found: articles"

    def test_leading_number_that_is_not_a_lone_token_is_not_a_code(self):
        # "4007:" does not consume the whole token, so the server treats the
        # payload as a legacy message; the client must agree.
        error = parse_error_frame("ERROR 4007: Table not found")

        assert error.error_code is None
        assert error.message == "4007: Table not found"

    def test_zero_is_not_a_code(self):
        error = parse_error_frame("ERROR 0 something")

        assert error.error_code is None
        assert error.message == "0 something"

    def test_out_of_range_code_is_not_a_code(self):
        error = parse_error_frame("ERROR 70000 something")

        assert error.error_code is None
        assert error.message == "70000 something"

    def test_coded_frame_without_a_message(self):
        error = parse_error_frame("ERROR 4007")

        assert error.error_code == ErrorCode.TABLE_NOT_FOUND
        assert error.message == ""

    @pytest.mark.parametrize(
        "code,expected",
        [
            (7, AuthenticationError),
            (6028, ServerNotReadyError),
            (6029, ServerNotReadyError),
            (6030, ServerBusyError),
            (3006, ServerError),
        ],
    )
    def test_code_selects_the_specific_exception(self, code, expected):
        error = parse_error_frame(f"ERROR {code} boom")

        assert type(error) is expected
        assert isinstance(error, ServerError)

    def test_transient_flag_follows_the_code(self):
        assert parse_error_frame("ERROR 6030 busy").is_transient
        assert parse_error_frame("ERROR 6028 loading").is_transient
        assert not parse_error_frame("ERROR 4007 gone").is_transient
        assert not parse_error_frame("ERROR legacy text").is_transient

    def test_str_surfaces_the_code(self):
        assert str(parse_error_frame("ERROR 4007 gone")) == "[4007] gone"
        assert str(parse_error_frame("ERROR gone")) == "gone"

    async def test_coded_frame_from_a_command_raises_the_typed_exception(self):
        async with FakeMygramServer() as server:
            server.admin_token = "s3cret"
            client = MygramClient(
                ClientConfig(host=server.host, port=server.port)
            )
            await client.connect()
            try:
                with pytest.raises(AuthenticationError) as excinfo:
                    await client.send_command("AUTH wrong")
            finally:
                await client.disconnect()

        assert excinfo.value.error_code == ErrorCode.PERMISSION_DENIED
        assert excinfo.value.message == "Authentication failed"

    async def test_untyped_frame_from_a_command_raises_plain_server_error(self):
        async with FakeMygramServer() as server:
            client = MygramClient(
                ClientConfig(host=server.host, port=server.port)
            )
            await client.connect()
            try:
                with pytest.raises(ServerError) as excinfo:
                    await client.send_command("NONSENSE")
            finally:
                await client.disconnect()

        assert type(excinfo.value) is ServerError
        assert excinfo.value.error_code is None
        assert excinfo.value.message == "unknown command"


class TestRetryPolicyDefaults:
    """Which errors the default policy considers worth resending."""

    def test_transient_server_states_are_retryable(self):
        policy = RetryPolicy()

        assert policy.is_retryable(ServerNotReadyError("loading", 6028))
        assert policy.is_retryable(ServerBusyError("busy", 6030))

    def test_request_shape_faults_are_not_retryable(self):
        policy = RetryPolicy()

        assert not policy.is_retryable(ServerError("bad filter", 3006))
