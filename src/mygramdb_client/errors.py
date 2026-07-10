"""Custom exception classes for MygramDB client."""
import builtins


class MygramError(Exception):
    """Base exception for all MygramDB errors."""

    def __init__(self, message: str, code: str = "MYGRAM_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ConnectionError(MygramError, builtins.ConnectionError):
    """Raised when connection to MygramDB server fails.

    Also subclasses the builtin :class:`ConnectionError` (an ``OSError``) so
    ``except ConnectionError`` catches it whether the caller means the builtin
    or this class — importing this name does not silently shadow the builtin's
    behavior.
    """

    def __init__(self, message: str):
        super().__init__(message, "CONNECTION_ERROR")


class ProtocolError(MygramError):
    """Raised when server returns an invalid or unexpected response."""

    def __init__(self, message: str):
        super().__init__(message, "PROTOCOL_ERROR")


class TimeoutError(MygramError, builtins.TimeoutError):
    """Raised when a command times out.

    Also subclasses the builtin :class:`TimeoutError`. On Python 3.11+ that is
    the same class as :class:`asyncio.TimeoutError`, so ``except TimeoutError``
    (builtin or asyncio) catches it as well as ``except MygramError``.
    """

    def __init__(self, message: str):
        super().__init__(message, "TIMEOUT_ERROR")


class InputValidationError(MygramError):
    """Raised when input validation fails (e.g., control characters, length)."""

    def __init__(self, message: str):
        super().__init__(message, "INPUT_VALIDATION_ERROR")


class ServerError(MygramError):
    """Raised when server returns an error response."""

    def __init__(self, message: str):
        super().__init__(message, "SERVER_ERROR")


class PoolTimeoutError(TimeoutError):
    """Raised when acquiring a pooled connection exceeds ``acquire_timeout``.

    Subclasses :class:`TimeoutError` so existing ``except TimeoutError`` (or
    ``except MygramError``) handlers still catch it.
    """

    def __init__(self, message: str):
        MygramError.__init__(self, message, "POOL_TIMEOUT_ERROR")


class PoolExhaustedError(MygramError):
    """Raised when the pool's waiter queue is already at ``max_pending``."""

    def __init__(self, message: str):
        super().__init__(message, "POOL_EXHAUSTED_ERROR")


class PoolClosedError(MygramError):
    """Raised when acquiring from a pool that has been closed."""

    def __init__(self, message: str):
        super().__init__(message, "POOL_CLOSED_ERROR")


class CircuitOpenError(MygramError):
    """Raised without touching the network while the circuit breaker is open."""

    def __init__(self, message: str):
        super().__init__(message, "CIRCUIT_OPEN_ERROR")
