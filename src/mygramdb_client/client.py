"""
MygramDB Client Implementation.

This module provides an async client for connecting to and querying MygramDB servers.
"""
import asyncio
from typing import Dict, List, Optional

from .command_utils import (
    ensure_query_length_within_limit,
    ensure_safe_command_value,
    ensure_safe_filters,
    ensure_safe_string_array,
    escape_query_string,
    validate_facet_column,
    validate_fuzzy,
    validate_highlight,
    validate_identifier,
)
from .errors import ConnectionError, ProtocolError, ServerError, TimeoutError
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
    ReplicationStatus,
    SearchOptions,
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

        Raises:
            ConnectionError: If connection fails.
        """
        if self._connected:
            return

        try:
            if self.config.socket_path:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(self.config.socket_path),
                    timeout=self.config.timeout,
                )
            else:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.config.host, self.config.port),
                    timeout=self.config.timeout,
                )
            self._connected = True
        except asyncio.TimeoutError:
            raise TimeoutError("Connection timeout")
        except OSError as e:
            raise ConnectionError(f"Failed to connect: {e}")

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

    async def search(
        self,
        table: str,
        query: str,
        options: Optional[SearchOptions] = None,
    ) -> SearchResponse:
        """
        Search for documents in a table.

        Args:
            table: Table name to search in.
            query: Search query text.
            options: Search options including limit, offset, and_terms, not_terms,
                     filters, sort_column, and sort_desc.

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

        parts: List[str] = ["SEARCH", table, escape_query_string(query)]

        # Add AND terms
        for term in opts.and_terms:
            parts.extend(["AND", escape_query_string(term)])

        # Add NOT terms
        for term in opts.not_terms:
            parts.extend(["NOT", escape_query_string(term)])

        # Add filters
        for key, value in opts.filters.items():
            parts.extend(["FILTER", key, "=", escape_query_string(value)])

        # Add sort (use _score for BM25 in MygramDB v1.6+)
        if opts.sort_column:
            parts.extend(["SORT", opts.sort_column, "DESC" if opts.sort_desc else "ASC"])

        # Add fuzzy (MygramDB v1.6+)
        if opts.fuzzy > 0:
            parts.extend(["FUZZY", str(opts.fuzzy)])

        # Add highlight (MygramDB v1.6+)
        if opts.highlight is not None:
            parts.append("HIGHLIGHT")
            open_tag = opts.highlight.open_tag or ""
            close_tag = opts.highlight.close_tag or ""
            if open_tag != "" and close_tag != "":
                parts.extend(["TAG", open_tag, close_tag])
            if opts.highlight.snippet_len and opts.highlight.snippet_len > 0:
                parts.extend(["SNIPPET_LEN", str(opts.highlight.snippet_len)])
            if opts.highlight.max_fragments and opts.highlight.max_fragments > 0:
                parts.extend(["MAX_FRAGMENTS", str(opts.highlight.max_fragments)])

        # Add limit and offset
        if opts.offset > 0 and opts.limit > 0:
            parts.extend(["LIMIT", f"{opts.offset},{opts.limit}"])
        elif opts.offset > 0:
            # offset > 0 with limit == 0: emit bare OFFSET so the server
            # actually skips records instead of returning the first page
            parts.extend(["OFFSET", str(opts.offset)])
        elif opts.limit > 0:
            parts.extend(["LIMIT", str(opts.limit)])

        response = await self.send_command(" ".join(parts))
        return self._parse_search_response(response)

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
        for key, value in opts.filters.items():
            parts.extend(["FILTER", key, "=", escape_query_string(value)])

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
        ensure_safe_command_value(filepath, "filepath")
        cmd = f"DUMP SAVE {filepath}" if filepath else "DUMP SAVE"
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
        ensure_safe_command_value(filepath, "filepath")
        cmd = f"DUMP LOAD {filepath}" if filepath else "DUMP LOAD"
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
        ensure_safe_command_value(filepath, "filepath")
        response = await self.send_command(f"DUMP VERIFY {filepath}")
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
        ensure_safe_command_value(filepath, "filepath")
        response = await self.send_command(f"DUMP INFO {filepath}")
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

        Args:
            table: Table name.
            column: Filter column to aggregate.
            options: Optional query, refinements and limit.

        Returns:
            FacetResponse with facet values and counts.

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
        ensure_query_length_within_limit(
            opts.query,
            self.config.max_query_length,
            opts.and_terms,
            opts.not_terms,
        )

        parts: List[str] = ["FACET", table, column]

        if opts.query:
            parts.extend(["QUERY", escape_query_string(opts.query)])
            for term in opts.and_terms:
                parts.extend(["AND", escape_query_string(term)])
            for term in opts.not_terms:
                parts.extend(["NOT", escape_query_string(term)])
            for key, value in opts.filters.items():
                parts.extend(["FILTER", key, "=", escape_query_string(value)])

        if opts.limit > 0:
            parts.extend(["LIMIT", str(opts.limit)])

        response = await self.send_command(" ".join(parts))
        return self._parse_facet_response(response)

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
        if not self._connected or not self._writer or not self._reader:
            raise ConnectionError("Not connected to server")

        async with self._get_command_lock():
            try:
                # Send command
                self._writer.write(f"{command}\r\n".encode("utf-8"))
                await self._writer.drain()

                # Read response
                response = await self._read_response()

                # Normalize CRLF to LF
                response = response.replace("\r\n", "\n").strip()

                # Check for error response
                if response.startswith("ERROR "):
                    raise ServerError(response[6:])

                return response

            except asyncio.TimeoutError:
                raise TimeoutError("Command timeout")
            except OSError as e:
                self._connected = False
                raise ConnectionError(f"Connection error: {e}")

    async def _read_response(self) -> str:
        """Read complete response from server."""
        buffer = ""

        while True:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(self.config.recv_buffer_size),
                    timeout=self.config.timeout,
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Read timeout")

            if not data:
                raise ConnectionError("Connection closed by server")

            buffer += data.decode("utf-8")

            # Check if response is complete
            if self._is_response_complete(buffer):
                return buffer

    # Multi-line response prefixes that terminate with "END\r\n" (or "END\n").
    # Matched against the first line of the buffer; the suffix is the value
    # ``True`` when the prefix is exact and ``False`` when a trailing payload
    # (e.g. filepath after "OK DUMP_INFO ") is allowed.
    _END_TERMINATED_PREFIXES = (
        ("OK INFO", True),
        ("OK REPLICATION", True),
        ("OK CACHE_STATS", True),
        ("OK DUMP_STATUS", True),
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

        Format::

            OK FACET <num_values>
            <value1>\\t<count1>
            <value2>\\t<count2>
            ...

        Lines starting with ``#`` (debug/comment) are ignored.
        """
        lines = response.split("\n")
        first_line = lines[0]

        if not first_line.startswith("OK FACET"):
            raise ProtocolError(f"Invalid FACET response: {first_line}")

        header_parts = first_line.split(" ")
        if len(header_parts) < 3:
            raise ProtocolError("Invalid FACET response: missing count")
        try:
            int(header_parts[2])
        except ValueError:
            raise ProtocolError(f"Invalid FACET count: {header_parts[2]}")

        results: List[FacetValue] = []
        for line in lines[1:]:
            if line == "" or line.startswith("#"):
                continue
            tab = line.find("\t")
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

        return FacetResponse(results=results)

    @staticmethod
    def _parse_count_response(response: str) -> CountResponse:
        """Parse COUNT response."""
        lines = response.split("\n")
        first_line = lines[0]

        if not first_line.startswith("OK COUNT "):
            raise ProtocolError(f"Invalid COUNT response: {first_line}")

        count = int(first_line.split(" ")[2])

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

            return ReplicationStatus(
                running=running,
                gtid=gtid,
                status_str=response,
                processed_events=processed_events,
                queue_size=queue_size,
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
                debug.query_time_ms = float(value)
            elif key == "index_time":
                debug.index_time_ms = float(value)
            elif key == "filter_time":
                debug.filter_time_ms = float(value)
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
                debug.cache_age_ms = float(value)
            elif key == "cache_saved_ms":
                debug.cache_saved_ms = float(value)
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
