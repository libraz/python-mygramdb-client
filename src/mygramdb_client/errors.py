"""Custom exception classes and protocol error codes for MygramDB client."""
import builtins
from enum import IntEnum
from typing import Optional


class ErrorCode(IntEnum):
    """
    Numeric error codes carried by the server's ``ERROR`` frames
    (MygramDB v1.10+).

    Codes are grouped into per-module ranges, mirroring the server's own
    taxonomy:

    - 0-999: general
    - 1000-1999: configuration
    - 2000-2999: MySQL / replication
    - 3000-3999: query parsing
    - 4000-4999: index / search
    - 5000-5999: storage / dump
    - 6000-6999: network / server
    - 7000-7999: client
    - 8000-8999: cache

    A server older than v1.10 sends untyped ``ERROR <message>`` frames; in that
    case :attr:`ServerError.error_code` is ``None``.
    """

    # General (0-999)
    UNKNOWN = 1
    INVALID_ARGUMENT = 2
    OUT_OF_RANGE = 3
    NOT_IMPLEMENTED = 4
    INTERNAL_ERROR = 5
    IO_ERROR = 6
    PERMISSION_DENIED = 7
    NOT_FOUND = 8
    ALREADY_EXISTS = 9
    TIMEOUT = 10
    CANCELLED = 11

    # Configuration (1000-1999)
    CONFIG_FILE_NOT_FOUND = 1000
    CONFIG_PARSE_ERROR = 1001
    CONFIG_VALIDATION_ERROR = 1002
    CONFIG_MISSING_REQUIRED = 1003
    CONFIG_INVALID_VALUE = 1004
    CONFIG_SCHEMA_ERROR = 1005
    CONFIG_YAML_ERROR = 1006
    CONFIG_JSON_ERROR = 1007

    # MySQL / replication (2000-2999)
    MYSQL_CONNECTION_FAILED = 2000
    MYSQL_QUERY_FAILED = 2001
    MYSQL_DISCONNECTED = 2002
    MYSQL_AUTH_FAILED = 2003
    MYSQL_TIMEOUT = 2004
    MYSQL_INVALID_GTID = 2005
    MYSQL_GTID_NOT_ENABLED = 2006
    MYSQL_REPLICATION_ERROR = 2007
    MYSQL_BINLOG_ERROR = 2008
    MYSQL_TABLE_NOT_FOUND = 2009
    MYSQL_COLUMN_NOT_FOUND = 2010
    MYSQL_DUPLICATE_COLUMN = 2011
    MYSQL_INVALID_SCHEMA = 2012
    MYSQL_FIELD_TRUNCATED = 2013
    MYSQL_INVALID_METADATA = 2014
    MYSQL_UNSUPPORTED_TYPE = 2015
    MYSQL_BINLOG_CHECKSUM_MISMATCH = 2016
    MYSQL_UNDECODABLE_BINLOG_EVENT = 2017
    MARIADB_INVALID_GTID = 2020
    MARIADB_PROTOCOL_ERROR = 2021
    MARIADB_UNSUPPORTED_VERSION = 2022

    # Query parsing (3000-3999)
    QUERY_SYNTAX_ERROR = 3000
    QUERY_INVALID_TOKEN = 3001
    QUERY_UNEXPECTED_TOKEN = 3002
    QUERY_MISSING_OPERAND = 3003
    QUERY_INVALID_OPERATOR = 3004
    QUERY_TOO_LONG = 3005
    QUERY_INVALID_FILTER = 3006
    QUERY_INVALID_SORT = 3007
    QUERY_INVALID_LIMIT = 3008
    QUERY_INVALID_OFFSET = 3009
    QUERY_EXPRESSION_PARSE_ERROR = 3010
    QUERY_AST_BUILD_ERROR = 3011

    # Index / search (4000-4999)
    INDEX_NOT_FOUND = 4000
    INDEX_CORRUPTED = 4001
    INDEX_SERIALIZATION_FAILED = 4002
    INDEX_DESERIALIZATION_FAILED = 4003
    INDEX_DOCUMENT_NOT_FOUND = 4004
    INDEX_INVALID_DOC_ID = 4005
    INDEX_FULL = 4006
    TABLE_NOT_FOUND = 4007
    CATALOG_NOT_INITIALIZED = 4008
    SYNC_TABLE_NOT_FOUND = 4010
    SYNC_ALREADY_IN_PROGRESS = 4011
    SYNC_MEMORY_CRITICAL = 4012
    SYNC_THREAD_CREATION_FAILED = 4013
    SYNC_MANAGER_NULL = 4014

    # Storage / dump (5000-5999)
    STORAGE_FILE_NOT_FOUND = 5000
    STORAGE_READ_ERROR = 5001
    STORAGE_WRITE_ERROR = 5002
    STORAGE_CORRUPTED = 5003
    STORAGE_CRC_MISMATCH = 5004
    STORAGE_VERSION_MISMATCH = 5005
    STORAGE_COMPRESSION_FAILED = 5006
    STORAGE_DECOMPRESSION_FAILED = 5007
    STORAGE_INVALID_FORMAT = 5008
    STORAGE_SNAPSHOT_BUILD_FAILED = 5009
    STORAGE_DOC_ID_EXHAUSTED = 5010
    STORAGE_DUMP_READ_ERROR = 5011
    STORAGE_DUMP_WRITE_ERROR = 5012

    # Network / server (6000-6999)
    NETWORK_BIND_FAILED = 6000
    NETWORK_LISTEN_FAILED = 6001
    NETWORK_ACCEPT_FAILED = 6002
    NETWORK_CONNECTION_REFUSED = 6003
    NETWORK_CONNECTION_CLOSED = 6004
    NETWORK_SEND_FAILED = 6005
    NETWORK_RECEIVE_FAILED = 6006
    NETWORK_INVALID_REQUEST = 6007
    NETWORK_PROTOCOL_ERROR = 6008
    NETWORK_SERVER_NOT_STARTED = 6010
    NETWORK_ALREADY_RUNNING = 6011
    NETWORK_SOCKET_CREATION_FAILED = 6012
    NETWORK_INVALID_BIND_ADDRESS = 6013
    NETWORK_UNIX_SOCKET_PATH_TOO_LONG = 6014
    NETWORK_UNIX_SOCKET_STALE = 6015
    NETWORK_REACTOR_UNSUPPORTED = 6016
    NETWORK_REACTOR_INIT_FAILED = 6017
    NETWORK_REACTOR_REGISTER_FAILED = 6018
    NETWORK_REACTOR_MODIFY_FAILED = 6019
    NETWORK_REACTOR_REMOVE_FAILED = 6020
    NETWORK_REACTOR_POLL_FAILED = 6021
    NETWORK_REACTOR_ALREADY_OPEN = 6023
    NETWORK_NULL_DEPENDENCY = 6024
    NETWORK_ACCEPTOR_NO_HANDLER = 6025
    SERVER_INIT_MISSING_DEPENDENCY = 6026
    SERVER_SHUTTING_DOWN = 6027
    SERVER_LOADING = 6028
    SERVER_NOT_READY = 6029
    SERVER_BUSY = 6030

    # Client (7000-7999)
    CLIENT_NOT_CONNECTED = 7000
    CLIENT_CONNECTION_FAILED = 7001
    CLIENT_SEND_FAILED = 7002
    CLIENT_RECEIVE_FAILED = 7003
    CLIENT_INVALID_RESPONSE = 7004
    CLIENT_TIMEOUT = 7005
    CLIENT_ALREADY_CONNECTED = 7006
    CLIENT_COMMAND_FAILED = 7007
    CLIENT_CONNECTION_CLOSED = 7008
    CLIENT_INVALID_ARGUMENT = 7009
    CLIENT_SERVER_ERROR = 7010
    CLIENT_PROTOCOL_ERROR = 7011
    CLIENT_EXPRESSION_PARSE_ERROR = 7012

    # Cache (8000-8999)
    CACHE_MISS = 8000
    CACHE_DISABLED = 8001
    CACHE_COMPRESSION_FAILED = 8002
    CACHE_DECOMPRESSION_FAILED = 8003
    CACHE_WORKER_START_FAILED = 8004


#: Codes describing a temporary server state: the same command may succeed on a
#: later attempt without any change to the request.
TRANSIENT_ERROR_CODES = frozenset(
    {
        ErrorCode.SERVER_LOADING,
        ErrorCode.SERVER_NOT_READY,
        ErrorCode.SERVER_BUSY,
    }
)


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
    """Raised when server returns an error response.

    ``error_code`` carries the numeric code from a MygramDB v1.10+ ``ERROR``
    frame, or ``None`` when the server sent an untyped frame. Prefer branching
    on the code over matching the message text: messages are free to change,
    codes are the protocol contract.
    """

    def __init__(self, message: str, error_code: Optional[int] = None):
        super().__init__(message, "SERVER_ERROR")
        self.error_code = error_code

    @property
    def is_transient(self) -> bool:
        """
        Whether the server reported a temporary state (loading, not ready, or
        busy) that an identical retry may clear. ``False`` for an untyped frame,
        which carries no reliable signal either way.
        """
        return self.error_code in TRANSIENT_ERROR_CODES

    def __str__(self) -> str:
        if self.error_code is None:
            return self.message
        return f"[{self.error_code}] {self.message}"


class AuthenticationError(ServerError):
    """
    Raised when ``AUTH`` is rejected, or an administrative command is issued on
    a connection that has not authenticated (MygramDB v1.10+, error code
    :attr:`ErrorCode.PERMISSION_DENIED`).

    Subclasses :class:`ServerError`, so existing handlers still catch it.
    """

    def __init__(self, message: str, error_code: Optional[int] = None):
        ServerError.__init__(self, message, error_code)
        self.code = "AUTHENTICATION_ERROR"


class ServerNotReadyError(ServerError):
    """
    Raised when the server is still loading or not yet ready to serve the
    request (MygramDB v1.10+, error codes :attr:`ErrorCode.SERVER_LOADING` and
    :attr:`ErrorCode.SERVER_NOT_READY`).

    Retryable: the same command may succeed once the server finishes coming up.
    """

    def __init__(self, message: str, error_code: Optional[int] = None):
        ServerError.__init__(self, message, error_code)
        self.code = "SERVER_NOT_READY_ERROR"


class ServerBusyError(ServerError):
    """
    Raised when the server's request capacity is temporarily exhausted — rate
    limiting, or a long-running operation holding the table (MygramDB v1.10+,
    error code :attr:`ErrorCode.SERVER_BUSY`).

    Retryable after a backoff.
    """

    def __init__(self, message: str, error_code: Optional[int] = None):
        ServerError.__init__(self, message, error_code)
        self.code = "SERVER_BUSY_ERROR"


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


def parse_error_frame(response: str) -> ServerError:
    """
    Decode a single-line ``ERROR`` frame into the most specific
    :class:`ServerError` subclass available.

    Mirrors the server's ``protocol::ParseErrorFrame``: the first token is read
    as a code only when it is a non-zero decimal that fits in a ``uint16`` and
    consumes the whole token. Anything else is an untyped (pre-v1.10) frame
    whose entire payload is the message.

    Args:
        response: Full response line, including the ``ERROR `` prefix.

    Returns:
        A :class:`ServerError` (or a subclass) ready to raise.
    """
    payload = response[len("ERROR "):] if response.startswith("ERROR ") else response

    separator = payload.find(" ")
    code_token = payload if separator < 0 else payload[:separator]

    code: Optional[int] = None
    if code_token.isdigit():
        parsed = int(code_token)
        if 0 < parsed <= 0xFFFF:
            code = parsed

    if code is None:
        return ServerError(payload)

    message = "" if separator < 0 else payload[separator + 1:]

    if code == ErrorCode.PERMISSION_DENIED:
        return AuthenticationError(message, code)
    if code in (ErrorCode.SERVER_LOADING, ErrorCode.SERVER_NOT_READY):
        return ServerNotReadyError(message, code)
    if code == ErrorCode.SERVER_BUSY:
        return ServerBusyError(message, code)
    return ServerError(message, code)
