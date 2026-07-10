"""Tests for exception hierarchy and builtin compatibility."""
import builtins

from mygramdb_client import ConnectionError, MygramError, TimeoutError
from mygramdb_client.errors import (
    PoolExhaustedError,
    PoolTimeoutError,
)


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
