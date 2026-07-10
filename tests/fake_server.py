"""
In-process fake MygramDB server for connection/pool tests.

Speaks just enough of the line protocol (SEARCH / COUNT / GET / INFO) to let the
real client and pool exercise connect, reconnect, and multiplexing against a
genuine socket instead of a mock.
"""
import asyncio
from typing import Optional


class FakeMygramServer:
    """A minimal MygramDB-protocol server bound to an ephemeral local port."""

    def __init__(self, response_delay: float = 0.0):
        self.host = "127.0.0.1"
        self.port: Optional[int] = None
        self._server: Optional[asyncio.AbstractServer] = None
        self.response_delay = response_delay
        # One-shot: delay only the next response (then revert to response_delay).
        self.delay_next_request = 0.0

        # Currently-open client writers, for simulating a server-side drop.
        self._writers: set = set()

        # Observability for assertions.
        self.connections = 0            # total accepted connections
        self.request_count = 0          # total commands handled
        self.commands: list = []        # every command line received (stripped)
        self.active = 0                 # currently in-flight handlers
        self.max_active = 0             # high-water mark of concurrent handlers

        # Override the raw bytes returned for a SEARCH command (e.g. to inject
        # a multibyte HIGHLIGHT payload).
        self.search_response: Optional[bytes] = None
        # One-shot: close the connection right after the next response.
        self.close_after_next_response = False
        # One-shot: read the next request then close without responding.
        self.drop_next_request = False
        # Persistent: close every request without responding.
        self.drop_always = False

    async def __aenter__(self) -> "FakeMygramServer":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, self.host, 0
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        self._writers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                self.commands.append(line.decode("utf-8").rstrip("\r\n"))
                if self.drop_always or self.drop_next_request:
                    self.drop_next_request = False
                    self.request_count += 1
                    break  # close without responding: client sees EOF on read
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    self.request_count += 1
                    delay = self.response_delay
                    if self.delay_next_request:
                        delay = self.delay_next_request
                        self.delay_next_request = 0.0
                    if delay:
                        await asyncio.sleep(delay)
                    response = self._respond(line.decode("utf-8").strip())
                    writer.write(response)
                    await writer.drain()
                finally:
                    self.active -= 1
                if self.close_after_next_response:
                    self.close_after_next_response = False
                    break
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    def sever_connections(self) -> int:
        """Forcibly close every open client connection, simulating a
        server-side restart or an idle connection dropped by the peer."""
        writers = list(self._writers)
        for writer in writers:
            try:
                writer.close()
            except Exception:
                pass
        return len(writers)

    def _respond(self, command: str) -> bytes:
        verb = command.split(" ", 1)[0].upper() if command else ""
        if verb == "SEARCH":
            if self.search_response is not None:
                return self.search_response
            return b"OK RESULTS 1 pk1\r\n"
        if verb == "COUNT":
            return b"OK COUNT 1\r\n"
        if verb == "GET":
            return b"OK DOC pk1 field=value\r\n"
        if verb == "INFO":
            return (
                b"OK INFO\r\n"
                b"version: 1.7.0\r\n"
                b"uptime_seconds: 10\r\n"
                b"total_documents: 1\r\n"
                b"END\r\n"
            )
        return b"ERROR unknown command\r\n"
