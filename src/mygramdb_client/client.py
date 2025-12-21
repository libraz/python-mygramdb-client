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
)
from .errors import ConnectionError, ProtocolError, ServerError, TimeoutError
from .types import (
    ClientConfig,
    CountOptions,
    CountResponse,
    DebugInfo,
    Document,
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
        client = MygramClient(ClientConfig(host='localhost', port=11016))
        await client.connect()

        result = await client.search('articles', 'hello world',
                                     SearchOptions(limit=100))
        print(f"Found {result.total_count} results")

        await client.disconnect()
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

    async def connect(self) -> None:
        """
        Connect to MygramDB server.

        Raises:
            ConnectionError: If connection fails.
        """
        if self._connected:
            return

        try:
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

        ensure_safe_command_value(table, "table")
        ensure_safe_command_value(query, "query")
        ensure_safe_string_array(opts.and_terms, "and_terms")
        ensure_safe_string_array(opts.not_terms, "not_terms")
        ensure_safe_filters(opts.filters)

        if opts.sort_column:
            ensure_safe_command_value(opts.sort_column, "sort_column")

        ensure_query_length_within_limit(
            query,
            self.config.max_query_length,
            opts.and_terms,
            opts.not_terms,
        )

        parts: List[str] = ["SEARCH", table, query]

        # Add AND terms
        for term in opts.and_terms:
            parts.extend(["AND", term])

        # Add NOT terms
        for term in opts.not_terms:
            parts.extend(["NOT", term])

        # Add filters
        for key, value in opts.filters.items():
            parts.extend(["FILTER", key, "=", value])

        # Add sort
        if opts.sort_column:
            parts.extend(["SORT", opts.sort_column, "DESC" if opts.sort_desc else "ASC"])

        # Add limit and offset
        if opts.offset > 0:
            parts.extend(["LIMIT", f"{opts.offset},{opts.limit}"])
        else:
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

        ensure_safe_command_value(table, "table")
        ensure_safe_command_value(query, "query")
        ensure_safe_string_array(opts.and_terms, "and_terms")
        ensure_safe_string_array(opts.not_terms, "not_terms")
        ensure_safe_filters(opts.filters)

        ensure_query_length_within_limit(
            query,
            self.config.max_query_length,
            opts.and_terms,
            opts.not_terms,
        )

        parts: List[str] = ["COUNT", table, query]

        # Add AND terms
        for term in opts.and_terms:
            parts.extend(["AND", term])

        # Add NOT terms
        for term in opts.not_terms:
            parts.extend(["NOT", term])

        # Add filters
        for key, value in opts.filters.items():
            parts.extend(["FILTER", key, "=", value])

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
        ensure_safe_command_value(table, "table")
        ensure_safe_command_value(primary_key, "primary_key")

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

    def _is_response_complete(self, buffer: str) -> bool:
        """Check if buffer contains a complete response."""
        # Multi-line responses end with empty line
        if (
            buffer.endswith("\n\n")
            or buffer.endswith("\r\n\r\n")
            or buffer.endswith("\n\r\n")
        ):
            return True

        # Multi-line INFO/CONFIG responses
        if "OK INFO\n" in buffer or "OK CONFIG\n" in buffer or buffer.startswith("+OK\n"):
            return (
                buffer.endswith("\n\n")
                or buffer.endswith("\r\n\r\n")
                or buffer.endswith("\n\r\n")
            )

        # Multi-line REPLICATION response
        if buffer.startswith("OK REPLICATION\n"):
            return "\nEND\n" in buffer or buffer.endswith("\nEND")

        # Debug response
        if "# DEBUG" in buffer:
            return (
                buffer.endswith("\n\n")
                or buffer.endswith("\r\n\r\n")
                or buffer.endswith("\n\r\n")
            )

        # Single-line response with newline
        lines = buffer.split("\n")
        if len(lines) > 1 and lines[-1] == "":
            return True

        return False

    @staticmethod
    def _parse_search_response(response: str) -> SearchResponse:
        """Parse SEARCH response."""
        lines = response.split("\n")
        first_line = lines[0]

        if not first_line.startswith("OK RESULTS "):
            raise ProtocolError(f"Invalid SEARCH response: {first_line}")

        parts = first_line.split(" ")
        total_count = int(parts[2])
        ids = parts[3:]

        results = [SearchResult(primary_key=id_) for id_ in ids]

        # Parse debug info if present
        debug = None
        try:
            debug_index = lines.index("# DEBUG")
            debug = MygramClient._parse_debug_info(lines[debug_index + 1:])
        except ValueError:
            pass

        return SearchResponse(results=results, total_count=total_count, debug=debug)

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
                elif key == "current_gtid":
                    gtid = value

            return ReplicationStatus(running=running, gtid=gtid, status_str=response)

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
            elif key == "limit":
                debug.limit = int(value.replace("(default)", "").strip())
            elif key == "offset":
                debug.offset = int(value.replace("(default)", "").strip())

        return debug


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
