"""
MygramDB Client Implementation.

This module provides an async client for connecting to and querying MygramDB servers.
"""
import asyncio
import re
import socket
import time
from dataclasses import replace
from typing import Dict, List, Optional

from .command_utils import (
    ensure_query_length_within_limit,
    ensure_safe_command_value,
    ensure_safe_filter_conditions,
    ensure_safe_filters,
    ensure_safe_string_array,
    escape_query_string,
    quote_command_argument,
    validate_facet_column,
    validate_fuzzy,
    validate_highlight,
    validate_identifier,
)
from .errors import (
    ConnectionError,
    InputValidationError,
    ProtocolError,
    TimeoutError,
    parse_error_frame,
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
    FilterCondition,
    HighlightOptions,
    QueryMode,
    ReplicationStatus,
    SearchOptions,
    SearchRawOptions,
    SearchResponse,
    SearchResult,
    ServerInfo,
)


class MygramClient:
    """
    MygramDB client for Python.

    This class provides a high-level async interface for connecting to and
    querying MygramDB servers.

    Example usage:
        async with MygramClient(ClientConfig(host='localhost', port=11016)) as client:
            result = await client.search('articles', 'hello world',
                                         SearchOptions(limit=100))
            print(f"Found {result.total_count} results")
    """

    def __init__(self, config: Optional[ClientConfig] = None):
        """
        Create a new MygramDB client.

        Args:
            config: Client configuration. Uses defaults if not provided.
        """
        self.config = config or ClientConfig()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        # Serializes concurrent send_command calls: a single TCP connection
        # carries one request/response stream, and interleaved writes/reads
        # would corrupt the protocol. Lazily created on first acquisition so
        # the construction does not require a running event loop.
        self._command_lock: Optional[asyncio.Lock] = None

    def _get_command_lock(self) -> asyncio.Lock:
        if self._command_lock is None:
            self._command_lock = asyncio.Lock()
        return self._command_lock

    async def __aenter__(self) -> "MygramClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """
        Connect to MygramDB server via TCP or Unix socket.

        When :attr:`ClientConfig.admin_token` is set, ``AUTH`` is issued on the
        fresh connection before it is handed back, so administrative commands
        work immediately (MygramDB v1.10+).

        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If the configured admin token is rejected.
        """
        if self._connected:
            return

        async with self._get_command_lock():
            # Another caller may have connected while this one waited.
            if self._connected:
                return
            await self._open_connection()
            await self._authenticate_if_configured()

    async def _open_connection(self) -> None:
        """
        Open the transport without authenticating. The caller holds the command
        lock and is responsible for the ``AUTH`` handshake.
        """
        try:
            if self.config.socket_path:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(self.config.socket_path),
                    timeout=self._connect_timeout(),
                )
            else:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.config.host, self.config.port),
                    timeout=self._connect_timeout(),
                )
                if self.config.tcp_keepalive:
                    self._apply_keepalive()
            self._connected = True
        except asyncio.TimeoutError:
            raise TimeoutError("Connection timeout")
        except OSError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    def _connect_timeout(self) -> float:
        """Effective connect timeout (``connect_timeout`` or ``timeout``)."""
        if self.config.connect_timeout is not None:
            return self.config.connect_timeout
        return self.config.timeout

    def _command_timeout(self) -> float:
        """Effective total response deadline (``command_timeout`` or ``timeout``)."""
        if self.config.command_timeout is not None:
            return self.config.command_timeout
        return self.config.timeout

    async def _authenticate_if_configured(self) -> None:
        """
        Issue ``AUTH`` when a token is configured. The caller holds the command
        lock, so this bypasses :meth:`send_command` and talks to the socket
        directly. A rejected or unexpected reply tears the connection down
        rather than leaving an unauthenticated socket that would fail later on
        the first administrative command.
        """
        token = self.config.admin_token
        if not token:
            return

        try:
            response = await self._exchange(
                f"AUTH {quote_command_argument(token, 'admin_token')}"
            )
            if not response.startswith("OK AUTHENTICATED"):
                raise ProtocolError(f"Invalid AUTH response: {response}")
        except BaseException:
            await self._drop_connection()
            raise

    async def _drop_connection(self) -> None:
        """Close the socket without waiting, and mark the client disconnected."""
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        self._connected = False

    async def authenticate(self, token: str) -> None:
        """
        Authenticate this connection for administrative commands
        (MygramDB v1.10+).

        Only needed for an ad-hoc token; setting
        :attr:`ClientConfig.admin_token` authenticates automatically on connect
        and on every transparent reconnect, which is what a long-lived client
        wants.

        Args:
            token: Administrative token (``api.admin_token`` on the server).

        Raises:
            AuthenticationError: If the server rejects the token.
            ProtocolError: If the reply is not an ``AUTH`` acknowledgement.
        """
        if token == "":
            raise InputValidationError("Input for token is empty")
        response = await self.send_command(
            f"AUTH {quote_command_argument(token, 'token')}"
        )
        if not response.startswith("OK AUTHENTICATED"):
            raise ProtocolError(f"Invalid AUTH response: {response}")

    def _apply_keepalive(self) -> None:
        """
        Enable TCP keepalive on the freshly opened socket. Best-effort: any
        option unsupported on the current platform is skipped rather than
        failing the connection.
        """
        if self._writer is None:
            return
        sock = self._writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            idle = self.config.tcp_keepalive_idle
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            elif hasattr(socket, "TCP_KEEPALIVE"):  # macOS name for KEEPIDLE
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, idle)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, idle)
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except OSError:
            pass

    async def disconnect(self) -> None:
        """Disconnect from server."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        self._connected = False

    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self._connected

    @staticmethod
    def _append_highlight_clause(
        parts: List[str], highlight: Optional[HighlightOptions]
    ) -> None:
        """
        Append the HIGHLIGHT clause (and its TAG / SNIPPET_LEN / MAX_FRAGMENTS
        sub-options) to a command's token list when highlight options are
        present (no-op when ``None``). MygramDB v1.6+.
        """
        if highlight is None:
            return
        parts.append("HIGHLIGHT")
        open_tag = highlight.open_tag or ""
        close_tag = highlight.close_tag or ""
        if open_tag != "" and close_tag != "":
            parts.extend(["TAG", open_tag, close_tag])
        if highlight.snippet_len and highlight.snippet_len > 0:
            parts.extend(["SNIPPET_LEN", str(highlight.snippet_len)])
        if highlight.max_fragments and highlight.max_fragments > 0:
            parts.extend(["MAX_FRAGMENTS", str(highlight.max_fragments)])

    @staticmethod
    def _append_filter_clauses(
        parts: List[str],
        filters: Dict[str, str],
        filter_conditions: List[FilterCondition],
    ) -> None:
        """
        Append every FILTER clause to a command's token list: the equality
        ``filters`` dict first, then the explicit-operator ``filter_conditions``
        (MygramDB v1.9+). Both forms use the same three-token wire shape
        ``FILTER <column> <op> <value>``.
        """
        for key, value in filters.items():
            parts.extend(["FILTER", key, "=", escape_query_string(value)])
        for condition in filter_conditions:
            operator = getattr(condition.op, "value", condition.op)
            parts.extend([
                "FILTER",
                condition.column,
                str(operator),
                escape_query_string(condition.value),
            ])

    @staticmethod
    def _append_limit_offset(parts: List[str], limit: int, offset: int) -> None:
        """
        Append the LIMIT / OFFSET clause to a command's token list.

        - ``limit > 0`` and ``offset > 0`` emits the atomic ``LIMIT <offset>,<limit>``.
        - ``limit > 0`` and ``offset == 0`` emits ``LIMIT <limit>``.
        - ``limit == 0`` and ``offset > 0`` emits a bare ``OFFSET <offset>`` so
          the server still skips the first ``<offset>`` results instead of
          silently dropping it.
        """
        if limit > 0 and offset > 0:
            parts.extend(["LIMIT", f"{offset},{limit}"])
        elif limit > 0:
            parts.extend(["LIMIT", str(limit)])
        elif offset > 0:
            parts.extend(["OFFSET", str(offset)])

    async def search(
        self,
        table: str,
        query: str,
        options: Optional[SearchOptions] = None,
    ) -> SearchResponse:
        """
        Search for documents in a table.

        By default ``query`` is literal text: reserved words such as ``AND`` or
        ``LIMIT`` are quoted so they match as terms. Set
        ``options.query_mode`` to :attr:`QueryMode.BOOLEAN` to have the server
        parse ``AND`` / ``OR`` / ``NOT`` and parentheses as operators while
        still applying filters, sorting, fuzzy matching and highlighting
        (MygramDB v1.10+) — something :meth:`search_raw` cannot express.

        Args:
            table: Table name to search in.
            query: Search query text, or a boolean expression when
                   ``options.query_mode`` is :attr:`QueryMode.BOOLEAN`.
            options: Search options including limit, offset, query_mode,
                     and_terms, not_terms, filters, filter_conditions,
                     sort_column, and sort_desc.

        Returns:
            Search response containing results array, total_count, and
            optional debug info.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        opts = options or SearchOptions()

        validate_identifier(table, "table name")
        ensure_safe_command_value(query, "query")
        ensure_safe_string_array(opts.and_terms, "and_terms")
        ensure_safe_string_array(opts.not_terms, "not_terms")
        ensure_safe_filters(opts.filters)
        for key in opts.filters:
            validate_identifier(key, "filter key")
        ensure_safe_filter_conditions(opts.filter_conditions)

        if opts.query_mode not in (QueryMode.LITERAL, QueryMode.BOOLEAN):
            raise InputValidationError(
                f"Invalid query_mode {opts.query_mode!r}: "
                f"must be one of {[m.value for m in QueryMode]}"
            )
        if opts.query_mode == QueryMode.BOOLEAN and query == "":
            raise InputValidationError(
                "Input for query must not be empty in boolean query mode"
            )

        if opts.sort_column:
            validate_identifier(opts.sort_column, "sort column")

        validate_fuzzy(opts.fuzzy)
        validate_highlight(opts.highlight)

        ensure_query_length_within_limit(
            query,
            self.config.max_query_length,
            opts.and_terms,
            opts.not_terms,
        )

        # Boolean mode sends the expression verbatim so the server's AST parser
        # sees the operators; quoting it would collapse the whole expression
        # into one literal phrase. It was validated above as non-empty and free
        # of control characters, so it cannot inject a second command.
        wire_query = (
            query if opts.query_mode == QueryMode.BOOLEAN
            else escape_query_string(query)
        )
        parts: List[str] = ["SEARCH", table, wire_query]

        # Add AND terms
        for term in opts.and_terms:
            parts.extend(["AND", escape_query_string(term)])

        # Add NOT terms
        for term in opts.not_terms:
            parts.extend(["NOT", escape_query_string(term)])

        # Add filters
        self._append_filter_clauses(parts, opts.filters, opts.filter_conditions)

        # Add sort (use _score for BM25 in MygramDB v1.6+). Without a column the
        # server orders by primary key descending, so only the ascending case
        # needs the bare `SORT ASC` shorthand.
        if opts.sort_column:
            parts.extend(["SORT", opts.sort_column, "DESC" if opts.sort_desc else "ASC"])
        elif not opts.sort_desc:
            parts.extend(["SORT", "ASC"])

        # Add fuzzy (MygramDB v1.6+)
        if opts.fuzzy > 0:
            parts.extend(["FUZZY", str(opts.fuzzy)])

        # Add highlight (MygramDB v1.6+)
        self._append_highlight_clause(parts, opts.highlight)

        # Add limit and offset
        self._append_limit_offset(parts, opts.limit, opts.offset)

        response = await self.send_command(" ".join(parts))
        return self._parse_search_response(response)

    async def search_with_highlights(
        self,
        table: str,
        query: str,
        options: Optional[SearchOptions] = None,
    ) -> SearchResponse:
        """
        :meth:`search` variant that requests highlighted snippets.

        Convenience wrapper that enables the HIGHLIGHT clause: any highlight
        options passed in ``options`` are preserved, otherwise server defaults
        are used. Snippets are returned in :attr:`SearchResult.snippet`.

        Args:
            table: Table name (bare or ``database.table``).
            query: Search query text.
            options: Search options.

        Returns:
            Search response with snippets.
        """
        opts = options or SearchOptions()
        highlight = opts.highlight if opts.highlight is not None else HighlightOptions()
        return await self.search(table, query, replace(opts, highlight=highlight))

    async def search_raw(
        self,
        table: str,
        raw_query: str,
        options: Optional[SearchRawOptions] = None,
    ) -> SearchResponse:
        """
        Search using a pre-built boolean expression (MygramDB v1.7+).

        The expression is sent verbatim (unquoted) so the server's AST parser
        can tokenize and interpret ``AND`` / ``OR`` / ``NOT`` / parentheses —
        including OR groups nested under AND (MygramDB v1.8+). Pair this with
        :func:`convert_search_expression` to preserve OR / grouping semantics
        that :meth:`search`'s AND/NOT decomposition cannot express.

        Args:
            table: Table name (bare or ``database.table``).
            raw_query: Pre-built boolean expression.
            options: Limit/offset/highlight options.

        Returns:
            Search response.

        Raises:
            InputValidationError: If the table or expression is invalid.
            ConnectionError: If not connected to server.
            ProtocolError: On server error or invalid response.

        Example:
            >>> raw = convert_search_expression("python OR (ruby AND rails)")
            >>> res = await client.search_raw("articles", raw,
            ...                                SearchRawOptions(limit=50))
        """
        opts = options or SearchRawOptions()

        validate_identifier(table, "table name")
        if raw_query == "":
            raise InputValidationError("Input for raw_query must not be empty")
        ensure_safe_command_value(raw_query, "raw_query")
        validate_highlight(opts.highlight)

        # Send the boolean expression verbatim (unquoted). escape_query_string
        # would wrap an expression containing whitespace in quotes, which the
        # server then treats as a single literal phrase, defeating AND/OR/NOT
        # tokenization and grouping (notably OR groups nested under AND). The
        # expression was validated above as non-empty and free of control
        # characters, so it cannot inject a second command. MygramDB v1.8+.
        parts: List[str] = ["SEARCH", table, raw_query]
        self._append_highlight_clause(parts, opts.highlight)
        self._append_limit_offset(parts, opts.limit, opts.offset)

        response = await self.send_command(" ".join(parts))
        return self._parse_search_response(response)

    async def search_raw_with_highlights(
        self,
        table: str,
        raw_query: str,
        options: Optional[SearchRawOptions] = None,
    ) -> SearchResponse:
        """
        :meth:`search_raw` variant that requests highlighted snippets.

        Equivalent to calling :meth:`search_raw` with a ``highlight`` option;
        any highlight options passed in ``options`` are preserved, otherwise
        server defaults are used.

        Args:
            table: Table name (bare or ``database.table``).
            raw_query: Pre-built boolean expression.
            options: Limit/offset/highlight options.

        Returns:
            Search response with snippets.
        """
        opts = options or SearchRawOptions()
        highlight = opts.highlight if opts.highlight is not None else HighlightOptions()
        return await self.search_raw(table, raw_query, replace(opts, highlight=highlight))

    async def count(
        self,
        table: str,
        query: str,
        options: Optional[CountOptions] = None,
    ) -> CountResponse:
        """
        Count matching documents in a table.

        Args:
            table: Table name to count documents in.
            query: Search query text.
            options: Count options including and_terms, not_terms, and filters.

        Returns:
            Count response containing count and optional debug info.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        opts = options or CountOptions()

        validate_identifier(table, "table name")
        ensure_safe_command_value(query, "query")
        ensure_safe_string_array(opts.and_terms, "and_terms")
        ensure_safe_string_array(opts.not_terms, "not_terms")
        ensure_safe_filters(opts.filters)
        for key in opts.filters:
            validate_identifier(key, "filter key")
        ensure_safe_filter_conditions(opts.filter_conditions)

        ensure_query_length_within_limit(
            query,
            self.config.max_query_length,
            opts.and_terms,
            opts.not_terms,
        )

        parts: List[str] = ["COUNT", table, escape_query_string(query)]

        # Add AND terms
        for term in opts.and_terms:
            parts.extend(["AND", escape_query_string(term)])

        # Add NOT terms
        for term in opts.not_terms:
            parts.extend(["NOT", escape_query_string(term)])

        # Add filters
        self._append_filter_clauses(parts, opts.filters, opts.filter_conditions)

        response = await self.send_command(" ".join(parts))
        return self._parse_count_response(response)

    async def get(self, table: str, primary_key: str) -> Document:
        """
        Get a document by its primary key.

        Args:
            table: Table name to retrieve document from.
            primary_key: Primary key value of the document.

        Returns:
            Document object containing primary_key and fields.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        validate_identifier(table, "table name")
        validate_identifier(primary_key, "primary key")

        response = await self.send_command(f"GET {table} {primary_key}")
        return self._parse_document_response(response)

    async def info(self) -> ServerInfo:
        """
        Get server information including version, uptime, and statistics.

        Returns:
            Server information object.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("INFO")
        return self._parse_info_response(response)

    async def get_config(self) -> str:
        """
        Get server configuration in YAML format.

        Returns:
            Configuration string in YAML format.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("CONFIG")

        # Handle both "+OK\n..." and "OK CONFIG\n..." formats
        if response.startswith("+OK\n"):
            return response[4:]
        if response.startswith("OK CONFIG\n"):
            return response[10:]

        raise ProtocolError(f"Invalid CONFIG response: {response}")

    async def get_replication_status(self) -> ReplicationStatus:
        """
        Get current replication status including running state and GTID position.

        Returns:
            Replication status object.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("REPLICATION STATUS")
        return self._parse_replication_status_response(response)

    async def stop_replication(self) -> None:
        """
        Stop binlog replication (index becomes read-only).

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("REPLICATION STOP")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to stop replication: {response}")

    async def start_replication(self) -> None:
        """
        Start binlog replication.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("REPLICATION START")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to start replication: {response}")

    async def enable_debug(self) -> None:
        """
        Enable debug mode for this connection to receive detailed query metrics.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("DEBUG ON")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to enable debug: {response}")

    async def disable_debug(self) -> None:
        """
        Disable debug mode for this connection.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        response = await self.send_command("DEBUG OFF")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to disable debug: {response}")

    async def dump_save(self, filepath: str) -> str:
        """
        Save index dump to server-side file.

        Args:
            filepath: File path on the server to save the dump.

        Returns:
            File path where the dump is being saved.
        """
        if filepath:
            cmd = f"DUMP SAVE {quote_command_argument(filepath, 'filepath')}"
        else:
            cmd = "DUMP SAVE"
        response = await self.send_command(cmd)
        if response.startswith("OK DUMP_STARTED "):
            return response[16:]
        if response.startswith("OK DUMP_SAVED "):
            return response[14:]
        raise ProtocolError(f"Invalid DUMP SAVE response: {response}")

    async def dump_load(self, filepath: str) -> None:
        """
        Load index from dump file.

        Args:
            filepath: File path on the server to load the dump from.
        """
        if filepath:
            cmd = f"DUMP LOAD {quote_command_argument(filepath, 'filepath')}"
        else:
            cmd = "DUMP LOAD"
        response = await self.send_command(cmd)
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to load dump: {response}")

    async def dump_status(self) -> DumpStatus:
        """Get status of a dump operation."""
        response = await self.send_command("DUMP STATUS")
        return self._parse_dump_status_response(response)

    async def dump_verify(self, filepath: str) -> str:
        """
        Verify integrity of a dump file.

        Args:
            filepath: File path of the dump to verify.

        Returns:
            Verification result message.
        """
        response = await self.send_command(
            f"DUMP VERIFY {quote_command_argument(filepath, 'filepath')}"
        )
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to verify dump: {response}")
        return response

    async def dump_info(self, filepath: str) -> str:
        """
        Get metadata about a dump file.

        Args:
            filepath: File path of the dump.

        Returns:
            Dump metadata string.
        """
        response = await self.send_command(
            f"DUMP INFO {quote_command_argument(filepath, 'filepath')}"
        )
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to get dump info: {response}")
        return response

    async def cache_stats(self) -> CacheStats:
        """Get cache statistics."""
        response = await self.send_command("CACHE STATS")
        return self._parse_cache_stats_response(response)

    async def cache_clear(self, table: Optional[str] = None) -> None:
        """
        Clear query cache.

        Args:
            table: If specified, only clear cache for this table.
                   If None, clear all caches.
        """
        if table:
            ensure_safe_command_value(table, "table")
            cmd = f"CACHE CLEAR {table}"
        else:
            cmd = "CACHE CLEAR"
        response = await self.send_command(cmd)
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to clear cache: {response}")

    async def cache_enable(self) -> None:
        """Enable query cache."""
        response = await self.send_command("CACHE ENABLE")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to enable cache: {response}")

    async def cache_disable(self) -> None:
        """Disable query cache."""
        response = await self.send_command("CACHE DISABLE")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to disable cache: {response}")

    async def optimize(self, table: Optional[str] = None) -> None:
        """
        Optimize index.

        Args:
            table: If specified, only optimize this table.
                   If None, optimize all tables.
        """
        if table:
            ensure_safe_command_value(table, "table")
            cmd = f"OPTIMIZE {table}"
        else:
            cmd = "OPTIMIZE"
        response = await self.send_command(cmd)
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to optimize: {response}")

    async def facet(
        self,
        table: str,
        column: str,
        options: Optional[FacetOptions] = None,
    ) -> FacetResponse:
        """
        Aggregate distinct filter-column values with document counts (MygramDB v1.6+).

        When ``options.query`` is empty, FACET returns the distinct values
        across the entire table. When provided, the aggregation is scoped
        to documents matching the query (with optional AND/NOT/FILTER refinements).

        ``options.limit`` and ``options.offset`` paginate the distinct values;
        :attr:`FacetResponse.total_count` reports how many exist in total
        (MygramDB v1.9+).

        Args:
            table: Table name.
            column: Filter column to aggregate.
            options: Optional query, refinements, limit and offset.

        Returns:
            FacetResponse with facet values, counts and the total distinct
            value count.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        opts = options or FacetOptions()

        validate_identifier(table, "table name")
        validate_facet_column(column)
        if opts.query:
            ensure_safe_command_value(opts.query, "query")
        ensure_safe_string_array(opts.and_terms, "and_terms")
        ensure_safe_string_array(opts.not_terms, "not_terms")
        ensure_safe_filters(opts.filters)
        for key in opts.filters:
            validate_identifier(key, "filter key")
        ensure_safe_filter_conditions(opts.filter_conditions)
        ensure_query_length_within_limit(
            opts.query,
            self.config.max_query_length,
            opts.and_terms,
            opts.not_terms,
        )

        # The search text follows the column directly; FACET has no keyword
        # introducing it. Refinements apply with or without one, so they are
        # emitted even for a whole-table facet.
        parts: List[str] = ["FACET", table, column]
        if opts.query:
            parts.append(escape_query_string(opts.query))
        for term in opts.and_terms:
            parts.extend(["AND", escape_query_string(term)])
        for term in opts.not_terms:
            parts.extend(["NOT", escape_query_string(term)])
        self._append_filter_clauses(parts, opts.filters, opts.filter_conditions)

        self._append_limit_offset(parts, opts.limit, opts.offset)

        response = await self.send_command(" ".join(parts))
        return self._parse_facet_response(response)

    async def set_variable(self, name: str, value: str) -> None:
        """
        Set a runtime variable (MygramDB v1.7+, MySQL-compatible ``SET``).

        The variable name is sent unquoted (validated as an identifier); the
        value is quoted when it contains whitespace or quote characters.

        Args:
            name: Runtime variable name (e.g. ``logging.level``).
            value: New value.

        Raises:
            ProtocolError: When the server rejects the assignment.
        """
        validate_identifier(name, "variable name")
        safe_value = quote_command_argument(value, "value")
        response = await self.send_command(f"SET {name} = {safe_value}")
        if not response.startswith("OK") and not response.startswith("+OK"):
            raise ProtocolError(f"Failed to set variable: {response}")

    async def show_variables(self, like_pattern: Optional[str] = None) -> str:
        """
        Show runtime variables (MygramDB v1.7+, MySQL-compatible
        ``SHOW VARIABLES``).

        Args:
            like_pattern: Optional MySQL LIKE pattern (e.g. ``logging%``).

        Returns:
            Raw variables table / ``+OK`` response from the server.
        """
        if not like_pattern:
            return await self.send_command("SHOW VARIABLES")
        safe_pattern = quote_command_argument(like_pattern, "like_pattern")
        return await self.send_command(f"SHOW VARIABLES LIKE {safe_pattern}")

    async def sync(self, table: str) -> str:
        """
        Start an on-demand sync (full reload) of a table (MygramDB v1.7+).

        Args:
            table: Table name (bare or ``database.table``).

        Returns:
            Server acknowledgement (e.g. ``OK SYNC STARTED ...``).

        Raises:
            ProtocolError: When the server rejects the request.
        """
        validate_identifier(table, "table name")
        response = await self.send_command(f"SYNC {table}")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to start sync: {response}")
        return response

    async def sync_status(self) -> str:
        """
        Get the status of in-flight / recent sync operations (MygramDB v1.7+).

        Returns:
            Raw ``SYNC_STATUS`` report from the server.

        Raises:
            ProtocolError: When the response is not a SYNC status response.
        """
        response = await self.send_command("SYNC STATUS")
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to get sync status: {response}")
        return response

    async def sync_stop(self, table: Optional[str] = None) -> str:
        """
        Stop a running sync (MygramDB v1.7+).

        With no table, stops every in-flight sync; with a table, stops only
        that table's sync.

        Args:
            table: Optional table name (bare or ``database.table``).

        Returns:
            Server acknowledgement.

        Raises:
            ProtocolError: When the server rejects the request.
        """
        if table:
            validate_identifier(table, "table name")
            cmd = f"SYNC STOP {table}"
        else:
            cmd = "SYNC STOP"
        response = await self.send_command(cmd)
        if not response.startswith("OK"):
            raise ProtocolError(f"Failed to stop sync: {response}")
        return response

    async def send_command(self, command: str) -> str:
        """
        Send raw command to server.

        This is a low-level interface for sending custom commands.
        Most users should use the higher-level methods instead.

        Args:
            command: Command string (without CRLF terminator).

        Returns:
            Response string from server.

        Raises:
            ConnectionError: If not connected to server.
            TimeoutError: If command times out.
            ProtocolError: If server returns an error.
        """
        if not self.config.auto_reconnect and (
            not self._connected or not self._writer or not self._reader
        ):
            raise ConnectionError("Not connected to server")

        async with self._get_command_lock():
            return await self._send_locked(command)

    async def _send_locked(self, command: str) -> str:
        """
        Send a single command and read its response while holding the command
        lock. With ``auto_reconnect``, a dead socket detected *before* the
        request is written triggers one reconnect-and-resend; a failure *after*
        the write is surfaced without resending (the command may have applied).
        """
        reconnected = False

        while True:
            if not self._connected or not self._writer or not self._reader:
                if self.config.auto_reconnect and not reconnected:
                    reconnected = True
                    await self._reconnect()
                else:
                    raise ConnectionError("Not connected to server")

            # Streams are live past the guard (either already open or just
            # re-established by _reconnect).
            assert self._writer is not None and self._reader is not None

            # Send phase: a failure here has written nothing the server acted
            # on, so it is safe to reconnect and resend once.
            try:
                await self._write_command(command)
            except asyncio.TimeoutError:
                raise TimeoutError("Command timeout")
            except OSError as e:
                self._connected = False
                if self.config.auto_reconnect and not reconnected:
                    reconnected = True
                    await self._reconnect()
                    continue
                raise ConnectionError(f"Connection error: {e}")

            # Read phase: past this point the command was delivered, so a
            # failure is reported rather than silently resent. Any read failure
            # also tears the connection down: a timed-out or aborted read may
            # leave the server's (late) response in the kernel buffer, and
            # reusing the socket would read that stale reply as the next
            # command's response. TimeoutError is caught explicitly rather than
            # via asyncio.TimeoutError, which is a distinct class before Python
            # 3.11 — matching on it there lets the custom TimeoutError fall
            # through to the OSError branch and be mis-reported as a
            # ConnectionError.
            try:
                response = await self._read_response()
            except TimeoutError:
                self._connected = False
                raise
            except ConnectionError:
                # EOF from _read_response: mark dead so the next call can heal.
                self._connected = False
                raise
            except ProtocolError:
                # The frame cap tripped: the rest of the oversized response is
                # still in flight, so the socket cannot be reused.
                self._connected = False
                raise
            except OSError as e:
                self._connected = False
                raise ConnectionError(f"Connection error: {e}")

            return self._decode_response(response)

    async def _write_command(self, command: str) -> None:
        """Write one command frame. The caller holds the command lock."""
        assert self._writer is not None
        self._writer.write(f"{command}\r\n".encode("utf-8"))
        await self._writer.drain()

    @staticmethod
    def _decode_response(response: str) -> str:
        """
        Normalize CRLF framing and turn an ``ERROR`` frame into the matching
        exception. A MygramDB v1.10+ frame carries a numeric code, which
        selects a specific :class:`ServerError` subclass; an untyped frame from
        an older server yields a plain :class:`ServerError`.
        """
        response = response.replace("\r\n", "\n").strip()
        if response.startswith("ERROR "):
            raise parse_error_frame(response)
        return response

    async def _exchange(self, command: str) -> str:
        """
        Send one command and return its decoded response, with no reconnect or
        resend. Used by the ``AUTH`` handshake, which runs while the command
        lock is already held and must not recurse into reconnect logic.
        """
        await self._write_command(command)
        return self._decode_response(await self._read_response())

    async def _reconnect(self) -> None:
        """
        Tear down any half-open socket and reconnect, re-authenticating when a
        token is configured. The caller holds the command lock, so this goes
        through the lock-free open path rather than :meth:`connect`.
        ``wait_closed`` is skipped so a dead socket cannot stall the reconnect.
        """
        await self._drop_connection()
        await self._open_connection()
        await self._authenticate_if_configured()

    async def _read_response(self) -> str:
        """Read complete response from server.

        Bytes are accumulated in place and decoded once the framing is
        complete. The completeness probe decodes leniently (``errors="ignore"``)
        so a multibyte character split across two reads cannot raise mid-stream;
        terminators are ASCII, so ignoring a trailing partial code point never
        hides one. The returned string is a strict decode of the full buffer.

        The timeout is one deadline for the whole response rather than a timer
        restarted by each partial read, so a server that trickles bytes cannot
        hold a command open indefinitely. ``max_response_bytes`` caps a single
        frame.
        """
        # Only reached from send_command, which guarantees a live connection.
        assert self._reader is not None
        buffer = bytearray()
        deadline = time.monotonic() + self._command_timeout()
        max_response_bytes = self.config.max_response_bytes

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Read timeout")

            try:
                data = await asyncio.wait_for(
                    self._reader.read(self.config.recv_buffer_size),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Read timeout")

            if not data:
                raise ConnectionError("Connection closed by server")

            buffer.extend(data)

            if 0 < max_response_bytes < len(buffer):
                raise ProtocolError(
                    f"Response exceeds max_response_bytes "
                    f"({max_response_bytes}): received {len(buffer)} bytes"
                )

            # Check if response is complete (lenient probe on partial bytes).
            probe = buffer.decode("utf-8", errors="ignore")
            if self._is_response_complete(probe):
                return buffer.decode("utf-8")

    # Multi-line response prefixes that terminate with "END\r\n" (or "END\n").
    # Matched against the first line of the buffer; the suffix is the value
    # ``True`` when the prefix is exact and ``False`` when a trailing payload
    # (e.g. filepath after "OK DUMP_INFO ") is allowed.
    _END_TERMINATED_PREFIXES = (
        ("OK INFO", True),
        ("OK REPLICATION", True),
        ("OK CACHE_STATS", True),
        ("OK DUMP_STATUS", True),
        ("OK SYNC_STATUS", True),
        ("OK DUMP_INFO", False),
    )

    def _is_response_complete(self, buffer: str) -> bool:
        """Check if buffer contains a complete response."""
        ends_with_blank = (
            buffer.endswith("\n\n")
            or buffer.endswith("\r\n\r\n")
            or buffer.endswith("\n\r\n")
        )

        ends_with_end_marker = (
            "\nEND\n" in buffer
            or "\nEND\r\n" in buffer
            or buffer.endswith("\nEND")
            or buffer.endswith("\r\nEND")
        )

        # First-line prefix detection for END-terminated multi-line responses
        # (INFO, REPLICATION, CACHE_STATS, DUMP_STATUS, DUMP_INFO).
        first_line = self._extract_first_line(buffer)
        if first_line is not None:
            for prefix, exact in self._END_TERMINATED_PREFIXES:
                if exact:
                    if first_line == prefix:
                        return ends_with_end_marker
                else:
                    # Prefix may be followed by a space + payload (e.g. filepath)
                    if first_line == prefix or first_line.startswith(prefix + " "):
                        return ends_with_end_marker

        # FACET response (MygramDB v1.6+) - multi-line, terminated by blank line
        if (buffer.startswith("OK FACET ")
                or buffer.startswith("OK FACET\r")
                or buffer.startswith("OK FACET\n")):
            return ends_with_blank

        # HIGHLIGHT response (MygramDB v1.6+) - SEARCH result with tab-prefixed
        # snippet payload lines, terminated by blank line
        if buffer.startswith("OK RESULTS ") and self._buffer_has_highlight_rows(buffer):
            return ends_with_blank

        # CONFIG (+OK ...) terminated by blank line
        if buffer.startswith("+OK"):
            return ends_with_blank

        # Generic multi-line response terminator
        if ends_with_blank:
            return True

        # Debug response
        if "# DEBUG" in buffer:
            return ends_with_blank

        # Single-line response with newline
        lines = buffer.split("\n")
        if len(lines) > 1 and lines[-1] == "":
            return True

        return False

    @staticmethod
    def _extract_first_line(buffer: str) -> Optional[str]:
        """Return the first line of the buffer (without CR/LF), or None."""
        # Find first \r\n or \n
        idx_crlf = buffer.find("\r\n")
        idx_lf = buffer.find("\n")
        if idx_crlf == -1 and idx_lf == -1:
            return None
        if idx_crlf != -1 and (idx_lf == -1 or idx_crlf <= idx_lf):
            return buffer[:idx_crlf]
        return buffer[:idx_lf]

    @staticmethod
    def _buffer_has_highlight_rows(buffer: str) -> bool:
        """
        Detect HIGHLIGHT-mode SEARCH responses by checking for tab-prefixed
        payload lines after the count line. Classic single-line responses
        never contain tabs.
        """
        first_line_end = buffer.find("\n")
        if first_line_end < 0:
            return False
        return "\t" in buffer[first_line_end + 1:]

    @staticmethod
    def _parse_search_response(response: str) -> SearchResponse:
        """
        Parse SEARCH response.

        Two formats are supported:

        1. Classic (single-line):
           ``OK RESULTS <total_count> <id1> <id2> ...``

        2. HIGHLIGHT (multi-line, MygramDB v1.6+):
           ::

               OK RESULTS <total_count>
               <id1>\\t<snippet1>
               <id2>\\t<snippet2>
               ...

        Either format may be followed by a ``# DEBUG`` block.
        """
        lines = response.split("\n")
        first_line = lines[0]

        if not first_line.startswith("OK RESULTS "):
            raise ProtocolError(f"Invalid SEARCH response: {first_line}")

        header_parts = first_line.split(" ")
        total_count = int(header_parts[2])

        # Collect payload lines that precede an optional # DEBUG block.
        payload_lines: List[str] = []
        debug_index = -1
        for i in range(1, len(lines)):
            line = lines[i]
            if line == "# DEBUG":
                debug_index = i
                break
            if line == "":
                continue
            payload_lines.append(line)

        results: List[SearchResult]
        if payload_lines:
            # HIGHLIGHT mode: each payload line is "<pk>[\t<snippet>]"
            results = []
            for line in payload_lines:
                tab = line.find("\t")
                if tab < 0:
                    results.append(SearchResult(primary_key=line, snippet=""))
                else:
                    results.append(SearchResult(
                        primary_key=line[:tab],
                        snippet=line[tab + 1:],
                    ))
        else:
            # Classic mode: PKs follow the count on the first line
            ids = header_parts[3:]
            results = [SearchResult(primary_key=id_) for id_ in ids]

        # Parse debug info if present
        debug = None
        if debug_index != -1:
            debug = MygramClient._parse_debug_info(lines[debug_index + 1:])

        return SearchResponse(results=results, total_count=total_count, debug=debug)

    @staticmethod
    def _parse_facet_response(response: str) -> FacetResponse:
        """
        Parse FACET response (MygramDB v1.6+).

        Format (MygramDB v1.9+)::

            OK FACET <page_values> <total_values>
            <value1>\\t<count1>
            <value2>\\t<count2>
            ...

        ``<page_values>`` is the number of rows in this page, ``<total_values>``
        the distinct value count before OFFSET and LIMIT. An older server emits
        only ``<page_values>``, in which case the total mirrors the page size.

        Comment lines (``#`` with no tab) are ignored. A facet value may itself
        start with ``#``; such a row still carries a tab separating the value
        from its count, so it is kept (MygramDB v1.8+).
        """
        lines = response.split("\n")
        first_line = lines[0]

        if not first_line.startswith("OK FACET"):
            raise ProtocolError(f"Invalid FACET response: {first_line}")

        header_parts = first_line.split(" ")
        if len(header_parts) < 3:
            raise ProtocolError("Invalid FACET response: missing count")
        try:
            page_count = int(header_parts[2])
        except ValueError:
            raise ProtocolError(f"Invalid FACET count: {header_parts[2]}")

        total_count = page_count
        if len(header_parts) > 3:
            try:
                total_count = int(header_parts[3])
            except ValueError:
                raise ProtocolError(
                    f"Invalid FACET total count: {header_parts[3]}"
                )

        results: List[FacetValue] = []
        for line in lines[1:]:
            tab = line.find("\t")
            if line == "" or (line.startswith("#") and tab < 0):
                continue
            if tab < 0:
                raise ProtocolError(f"Invalid FACET row: {line}")
            value = line[:tab]
            count_str = line[tab + 1:].strip()
            try:
                count = int(count_str)
            except ValueError:
                raise ProtocolError(
                    f"Invalid FACET count for {value}: {count_str}"
                )
            results.append(FacetValue(value=value, count=count))

        return FacetResponse(results=results, total_count=total_count)

    @staticmethod
    def _parse_count_response(response: str) -> CountResponse:
        """
        Parse COUNT response (``OK COUNT <n>``).

        Parsing is strict: the header must be exactly three tokens with a
        decimal count. A trailing token means the reply is not the response
        this command expects, and silently reading the third token would report
        a plausible-looking number from a frame that means something else.
        """
        lines = response.split("\n")
        first_line = lines[0]

        if not first_line.startswith("OK COUNT "):
            raise ProtocolError(f"Invalid COUNT response: {first_line}")

        header_parts = first_line.split(" ")
        if len(header_parts) != 3 or not header_parts[2].isdigit():
            raise ProtocolError(f"Invalid COUNT response: {first_line}")
        count = int(header_parts[2])

        # Parse debug info if present
        debug = None
        try:
            debug_index = lines.index("# DEBUG")
            debug = MygramClient._parse_debug_info(lines[debug_index + 1:])
        except ValueError:
            pass

        return CountResponse(count=count, debug=debug)

    @staticmethod
    def _parse_document_response(response: str) -> Document:
        """Parse GET response."""
        if not response.startswith("OK DOC "):
            raise ProtocolError(f"Invalid GET response: {response}")

        parts = response[7:].split(" ")
        primary_key = parts[0]
        fields: Dict[str, str] = {}

        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value

        return Document(primary_key=primary_key, fields=fields)

    @staticmethod
    def _parse_info_response(response: str) -> ServerInfo:
        """Parse INFO response."""
        if not response.startswith("OK INFO"):
            raise ProtocolError(f"Invalid INFO response: {response}")

        lines = response.split("\n")[1:]  # Skip "OK INFO" line
        info = ServerInfo()

        for line in lines:
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue

            if ":" not in trimmed:
                continue

            key, value = trimmed.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key == "version":
                info.version = value
            elif key == "uptime_seconds":
                info.uptime_seconds = int(value)
            elif key == "total_requests":
                info.total_requests = int(value)
            elif key == "connected_clients":
                info.active_connections = int(value)
            elif key == "used_memory_bytes":
                info.index_size_bytes = int(value)
            elif key == "total_documents":
                info.doc_count = int(value)
            elif key == "tables":
                info.tables = [s.strip() for s in value.split(",")]
            elif key == "data_initialized":
                info.data_initialized = value == "true"
            elif key == "readiness":
                info.ready = value == "ready"

        return info

    @staticmethod
    def _parse_replication_status_response(response: str) -> ReplicationStatus:
        """
        Parse REPLICATION STATUS response.

        Handles both single-line format:
            OK REPLICATION status=running gtid=xxx
        And multi-line format:
            OK REPLICATION
            status: running
            current_gtid: xxx
            processed_events: 123
            END

        The diagnostics keys a v1.10 server adds (``crc_errors``,
        ``schema_incompatible``, the ``last_error`` pair and the applied-progress
        timestamps) are read when present and left at their defaults otherwise,
        so one parser serves every server version.
        """
        if not response.startswith("OK REPLICATION"):
            raise ProtocolError(f"Invalid REPLICATION STATUS response: {response}")

        lines = response.split("\n")

        # Check if multi-line format (first line is just "OK REPLICATION")
        if lines[0].strip() == "OK REPLICATION":
            # Multi-line format
            running = False
            gtid = ""
            processed_events = 0
            queue_size = 0
            state = ""
            crc_errors = 0
            schema_incompatible = False
            last_error_code = 0
            last_error = ""
            last_applied_unixtime = 0
            seconds_since_last_applied: Optional[int] = None

            for line in lines[1:]:
                trimmed = line.strip()
                if not trimmed or trimmed == "END":
                    continue

                if ":" not in trimmed:
                    continue

                colon_index = trimmed.index(":")
                key = trimmed[:colon_index].strip()
                value = trimmed[colon_index + 1:].strip()

                if key == "status":
                    running = value == "running"
                    state = value
                elif key in ("current_gtid", "gtid"):
                    gtid = value
                elif key == "processed_events":
                    try:
                        processed_events = int(value)
                    except ValueError:
                        pass
                elif key == "queue_size":
                    try:
                        queue_size = int(value)
                    except ValueError:
                        pass
                elif key == "crc_errors":
                    try:
                        crc_errors = int(value)
                    except ValueError:
                        pass
                elif key == "schema_incompatible":
                    schema_incompatible = value == "true"
                elif key == "last_error_code":
                    # The server reports 0 for "no failure recorded", which is
                    # already this field's default, so it needs no special case.
                    try:
                        last_error_code = int(value)
                    except ValueError:
                        pass
                elif key == "last_error":
                    last_error = value
                elif key == "last_applied_unixtime":
                    try:
                        last_applied_unixtime = int(value)
                    except ValueError:
                        pass
                elif key == "seconds_since_last_applied":
                    # Passed through verbatim: the server's -1 means "no event
                    # applied yet", a sentinel rather than a lag of zero.
                    try:
                        seconds_since_last_applied = int(value)
                    except ValueError:
                        pass

            return ReplicationStatus(
                running=running,
                gtid=gtid,
                status_str=response,
                processed_events=processed_events,
                queue_size=queue_size,
                state=state,
                crc_errors=crc_errors,
                schema_incompatible=schema_incompatible,
                last_error_code=last_error_code,
                last_error=last_error,
                last_applied_unixtime=last_applied_unixtime,
                seconds_since_last_applied=seconds_since_last_applied,
            )

        # Single-line format: OK REPLICATION status=running gtid=xxx
        parts = response[15:].split(" ")
        running = False
        gtid = ""

        for part in parts:
            if part.startswith("status="):
                running = part.split("=")[1] == "running"
            elif part.startswith("gtid="):
                gtid = part.split("=")[1]

        return ReplicationStatus(running=running, gtid=gtid, status_str=response)

    @staticmethod
    def _parse_leading_float(value: str) -> float:
        """
        Parse the leading numeric portion of a value, tolerating a trailing
        unit suffix (e.g. the server emits debug timings as ``0.011ms``).

        Mirrors the lenient behaviour of JavaScript's ``parseFloat``; returns
        ``0.0`` when no numeric prefix is present.
        """
        match = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", value)
        return float(match.group(1)) if match else 0.0

    @staticmethod
    def _parse_debug_info(lines: List[str]) -> DebugInfo:
        """Parse debug info from response lines."""
        debug = DebugInfo()

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue

            if ":" not in trimmed:
                continue

            key, value = trimmed.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key == "query_time":
                debug.query_time_ms = MygramClient._parse_leading_float(value)
            elif key == "index_time":
                debug.index_time_ms = MygramClient._parse_leading_float(value)
            elif key == "filter_time":
                debug.filter_time_ms = MygramClient._parse_leading_float(value)
            elif key == "terms":
                debug.terms = int(value)
            elif key == "ngrams":
                debug.ngrams = int(value)
            elif key == "candidates":
                debug.candidates = int(value)
            elif key == "after_intersection":
                debug.after_intersection = int(value)
            elif key == "after_not":
                debug.after_not = int(value)
            elif key == "after_filters":
                debug.after_filters = int(value)
            elif key == "final":
                debug.final = int(value)
            elif key == "optimization":
                debug.optimization = value
            elif key == "sort":
                debug.sort = value
            elif key == "cache":
                debug.cache = value
            elif key == "cache_age_ms":
                debug.cache_age_ms = MygramClient._parse_leading_float(value)
            elif key == "cache_saved_ms":
                debug.cache_saved_ms = MygramClient._parse_leading_float(value)
            elif key == "cache_reason":
                debug.cache_reason = value
            elif key == "cache_cost_ms":
                debug.cache_cost_ms = MygramClient._parse_leading_float(value)
            elif key == "cache_key":
                debug.cache_key = value
            elif key == "highlight":
                debug.highlight = value == "on"
            elif key == "limit":
                debug.limit = int(value.replace("(default)", "").strip())
            elif key == "offset":
                debug.offset = int(value.replace("(default)", "").strip())

        return debug

    @staticmethod
    def _parse_dump_status_response(response: str) -> DumpStatus:
        """Parse DUMP STATUS response."""
        if not response.startswith("OK DUMP_STATUS"):
            raise ProtocolError(f"Invalid DUMP STATUS response: {response}")

        status = DumpStatus()
        lines = response.split("\n")[1:]

        for line in lines:
            trimmed = line.strip()
            if not trimmed or trimmed == "END":
                continue

            idx = trimmed.find(":")
            if idx < 0:
                continue

            key = trimmed[:idx].strip()
            value = trimmed[idx + 1:].strip()

            if key == "save_in_progress":
                status.save_in_progress = value == "true"
            elif key == "load_in_progress":
                status.load_in_progress = value == "true"
            elif key == "status":
                status.status = value
            elif key == "filepath":
                status.filepath = value
            elif key == "tables_processed":
                status.tables_processed = int(value)
            elif key == "tables_total":
                status.tables_total = int(value)
            elif key == "current_table":
                status.current_table = value
            elif key == "elapsed_seconds":
                status.elapsed_seconds = float(value)
            elif key == "result_filepath":
                status.result_filepath = value
            elif key == "error":
                status.error = value

        return status

    @staticmethod
    def _parse_cache_stats_response(response: str) -> CacheStats:
        """Parse CACHE STATS response."""
        if not response.startswith("OK CACHE_STATS"):
            raise ProtocolError(f"Invalid CACHE STATS response: {response}")

        stats = CacheStats()
        lines = response.split("\n")[1:]

        for line in lines:
            trimmed = line.strip()
            if not trimmed or trimmed == "END" or trimmed.startswith("#"):
                continue

            idx = trimmed.find(":")
            if idx < 0:
                continue

            key = trimmed[:idx].strip()
            value = trimmed[idx + 1:].strip()

            if key in ("enabled", "cache_enabled"):
                stats.enabled = value in ("true", "1")
            elif key in ("hits", "cache_hits"):
                stats.hits = int(value)
            elif key in ("misses", "cache_misses"):
                stats.misses = int(value)
            elif key in ("hit_rate", "cache_hit_rate"):
                stats.hit_rate = float(value.replace("%", ""))
            elif key in ("entries", "cache_current_entries", "current_entries"):
                stats.current_entries = int(value)
            elif key in ("memory_bytes", "cache_memory_bytes", "current_memory_bytes"):
                stats.memory_bytes = int(value)
            elif key in ("evictions", "cache_evictions"):
                stats.evictions = int(value)
            elif key == "max_memory_mb":
                stats.max_memory_mb = float(value)
            elif key == "current_memory_mb":
                stats.current_memory_mb = float(value)
            elif key == "ttl_seconds":
                stats.ttl_seconds = int(value)
            elif key == "total_queries":
                stats.total_queries = int(value)
            elif key == "invalidation_index_memory_bytes":
                stats.invalidation_index_memory_bytes = int(value)
            elif key == "invalidation_queue_memory_bytes":
                stats.invalidation_queue_memory_bytes = int(value)
            elif key == "accounted_memory_bytes":
                stats.accounted_memory_bytes = int(value)
            elif key == "ttl_expirations":
                stats.ttl_expirations = int(value)
            elif key == "rejection_count":
                stats.rejection_count = int(value)
            elif key == "rejection_oversize":
                stats.rejection_oversize = int(value)
            elif key == "rejection_memory_budget":
                stats.rejection_memory_budget = int(value)
            elif key == "rejection_duplicate":
                stats.rejection_duplicate = int(value)
            elif key == "stale_entry_removals":
                stats.stale_entry_removals = int(value)
            elif key == "decompression_failures":
                stats.decompression_failures = int(value)
            elif key == "stale_lru_entries":
                stats.stale_lru_entries = int(value)
            elif key == "invalidations_immediate":
                stats.invalidations_immediate = int(value)
            elif key == "invalidations_deferred":
                stats.invalidations_deferred = int(value)
            elif key == "invalidations_batches":
                stats.invalidations_batches = int(value)
            elif key == "avg_cache_hit_time_ms":
                stats.avg_cache_hit_time_ms = float(value)
            elif key == "avg_cache_miss_time_ms":
                stats.avg_cache_miss_time_ms = float(value)
            elif key == "total_time_saved_ms":
                stats.total_time_saved_ms = float(value)

        return stats


def create_mygram_client(config: Optional[ClientConfig] = None) -> MygramClient:
    """
    Create a new MygramDB client.

    This is a convenience function for creating client instances.

    Args:
        config: Client configuration. Uses defaults if not provided.

    Returns:
        A new MygramClient instance.
    """
    return MygramClient(config)
