"""Tests for timeout separation and TCP keepalive."""
import socket

import pytest

from mygramdb_client import ClientConfig, MygramClient
from mygramdb_client.errors import TimeoutError

from .fake_server import FakeMygramServer


class TestTimeoutConfig:
    def test_defaults_fall_back_to_timeout(self):
        config = ClientConfig(timeout=3.0)
        assert config.connect_timeout is None
        assert config.command_timeout is None
        client = MygramClient(config)
        assert client._connect_timeout() == 3.0
        assert client._command_timeout() == 3.0

    def test_explicit_values_override(self):
        config = ClientConfig(
            timeout=3.0, connect_timeout=0.5, command_timeout=10.0
        )
        client = MygramClient(config)
        assert client._connect_timeout() == 0.5
        assert client._command_timeout() == 10.0


async def test_command_timeout_trips_on_slow_response():
    async with FakeMygramServer(response_delay=0.3) as server:
        client = MygramClient(
            ClientConfig(
                host=server.host, port=server.port, command_timeout=0.05
            )
        )
        await client.connect()
        try:
            with pytest.raises(TimeoutError):
                await client.search("articles", "hello")
        finally:
            await client.disconnect()


async def test_read_timeout_drops_connection():
    """A read timeout must tear the socket down: the server's late response
    would otherwise be read as the next command's reply."""
    async with FakeMygramServer(response_delay=0.3) as server:
        client = MygramClient(
            ClientConfig(
                host=server.host, port=server.port, command_timeout=0.05
            )
        )
        await client.connect()
        try:
            with pytest.raises(TimeoutError):
                await client.search("articles", "hello")
            assert client.is_connected() is False
        finally:
            await client.disconnect()


async def test_keepalive_enabled_by_default():
    async with FakeMygramServer() as server:
        client = MygramClient(ClientConfig(host=server.host, port=server.port))
        await client.connect()
        try:
            sock = client._writer.get_extra_info("socket")
            # Enabled reports a nonzero value (the raw flag differs by platform).
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        finally:
            await client.disconnect()


async def test_keepalive_can_be_disabled():
    async with FakeMygramServer() as server:
        client = MygramClient(
            ClientConfig(
                host=server.host, port=server.port, tcp_keepalive=False
            )
        )
        await client.connect()
        try:
            sock = client._writer.get_extra_info("socket")
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 0
        finally:
            await client.disconnect()
