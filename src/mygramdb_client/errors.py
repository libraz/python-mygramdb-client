"""Custom exception classes for MygramDB client."""


class MygramError(Exception):
    """Base exception for all MygramDB errors."""

    def __init__(self, message: str, code: str = "MYGRAM_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ConnectionError(MygramError):
    """Raised when connection to MygramDB server fails."""

    def __init__(self, message: str):
        super().__init__(message, "CONNECTION_ERROR")


class ProtocolError(MygramError):
    """Raised when server returns an invalid or unexpected response."""

    def __init__(self, message: str):
        super().__init__(message, "PROTOCOL_ERROR")


class TimeoutError(MygramError):
    """Raised when a command times out."""

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
