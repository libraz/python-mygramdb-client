"""
MygramDB Client for Python.

A high-performance Python client for MygramDB - an in-memory full-text search engine
that is 25-200x faster than MySQL FULLTEXT with MySQL replication support.

Example usage:
    from mygramdb_client import MygramClient, ClientConfig, SearchOptions

    async def main():
        client = MygramClient(ClientConfig(host='localhost', port=11016))
        await client.connect()

        result = await client.search('articles', 'hello world',
                                     SearchOptions(limit=100))
        print(f"Found {result.total_count} results")

        await client.disconnect()
"""
from .client import MygramClient, create_mygram_client
from .command_utils import parse_table_identity, qualify_table_identity
from .errors import (
    TRANSIENT_ERROR_CODES,
    AuthenticationError,
    CircuitOpenError,
    ConnectionError,
    ErrorCode,
    InputValidationError,
    MygramError,
    PoolClosedError,
    PoolExhaustedError,
    PoolTimeoutError,
    ProtocolError,
    ServerBusyError,
    ServerError,
    ServerNotReadyError,
    TimeoutError,
)
from .pool import MygramPool, PooledConnection
from .search_expression import (
    SearchExpression,
    convert_search_expression,
    has_complex_expression,
    parse_search_expression,
    simplify_search_expression,
    to_query_string,
)
from .types import (
    CacheStats,
    CircuitBreakerConfig,
    ClientConfig,
    CountOptions,
    CountResponse,
    DebugInfo,
    Document,
    DumpStatus,
    FacetOptions,
    FacetResponse,
    FacetValue,
    FilterCondition,
    FilterOp,
    HighlightOptions,
    QueryMode,
    ReplicationStatus,
    SearchOptions,
    PoolConfig,
    PoolEvent,
    PoolStats,
    RetryPolicy,
    SearchRawOptions,
    SearchResponse,
    SearchResult,
    ServerInfo,
    SimplifiedExpression,
)

__version__ = "1.4.0"

__all__ = [
    # Client
    "MygramClient",
    "create_mygram_client",
    # Connection pool
    "MygramPool",
    "PooledConnection",
    "PoolConfig",
    "PoolStats",
    "PoolEvent",
    "RetryPolicy",
    "CircuitBreakerConfig",
    # Config and Options
    "ClientConfig",
    "SearchOptions",
    "SearchRawOptions",
    "CountOptions",
    "HighlightOptions",
    "FacetOptions",
    "QueryMode",
    "FilterOp",
    "FilterCondition",
    # Response types
    "SearchResponse",
    "SearchResult",
    "CountResponse",
    "Document",
    "ServerInfo",
    "ReplicationStatus",
    "DebugInfo",
    "DumpStatus",
    "CacheStats",
    "FacetResponse",
    "FacetValue",
    # Search expression
    "SearchExpression",
    "SimplifiedExpression",
    "parse_search_expression",
    "simplify_search_expression",
    "convert_search_expression",
    "has_complex_expression",
    "to_query_string",
    # Table identity helpers (v1.7+)
    "qualify_table_identity",
    "parse_table_identity",
    # Errors
    "MygramError",
    "ConnectionError",
    "ProtocolError",
    "TimeoutError",
    "InputValidationError",
    "ServerError",
    "AuthenticationError",
    "ServerNotReadyError",
    "ServerBusyError",
    "ErrorCode",
    "TRANSIENT_ERROR_CODES",
    "PoolTimeoutError",
    "PoolExhaustedError",
    "PoolClosedError",
    "CircuitOpenError",
]
