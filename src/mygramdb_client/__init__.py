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
from .errors import (
    ConnectionError,
    InputValidationError,
    MygramError,
    ProtocolError,
    ServerError,
    TimeoutError,
)
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
    ClientConfig,
    CountOptions,
    CountResponse,
    DebugInfo,
    Document,
    DumpStatus,
    FacetOptions,
    FacetResponse,
    FacetValue,
    HighlightOptions,
    ReplicationStatus,
    SearchOptions,
    SearchResponse,
    SearchResult,
    ServerInfo,
    SimplifiedExpression,
)

__version__ = "1.1.1"

__all__ = [
    # Client
    "MygramClient",
    "create_mygram_client",
    # Config and Options
    "ClientConfig",
    "SearchOptions",
    "CountOptions",
    "HighlightOptions",
    "FacetOptions",
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
    # Errors
    "MygramError",
    "ConnectionError",
    "ProtocolError",
    "TimeoutError",
    "InputValidationError",
    "ServerError",
]
