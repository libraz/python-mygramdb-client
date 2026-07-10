"""Tests for MygramClient.auto_reconnect against a real socket."""
import pytest

from mygramdb_client import ClientConfig, MygramClient
from mygramdb_client.errors import ConnectionError

from .fake_server import FakeMygramServer


async def test_config_default_no_auto_reconnect():
    config = ClientConfig()
    assert config.auto_reconnect is False


async def test_reconnect_resends_after_local_disconnect():
    """A command auto-reconnects when the client knows it is disconnected."""
    async with FakeMygramServer() as server:
        client = MygramClient(
            ClientConfig(
                host=server.host, port=server.port, auto_reconnect=True
            )
        )
        await client.connect()
        try:
            first = await client.search("articles", "hello")
            assert first.total_count == 1

            # Simulate a known-dead connection; the next command must reconnect.
            await client.disconnect()
            assert client.is_connected() is False

            second = await client.search("articles", "hello")
            assert second.total_count == 1
            assert client.is_connected() is True
            # Two physical connections: the original and the reconnect.
            assert server.connections == 2
        finally:
            await client.disconnect()


async def test_no_reconnect_raises_when_disabled():
    async with FakeMygramServer() as server:
        client = MygramClient(
            ClientConfig(
                host=server.host, port=server.port, auto_reconnect=False
            )
        )
        await client.connect()
        await client.disconnect()

        with pytest.raises(ConnectionError):
            await client.search("articles", "hello")


async def test_reconnect_heals_after_server_drop():
    """After the server drops mid-session, a later command reconnects."""
    async with FakeMygramServer() as server:
        client = MygramClient(
            ClientConfig(
                host=server.host, port=server.port, auto_reconnect=True
            )
        )
        await client.connect()
        try:
            server.close_after_next_response = True
            first = await client.search("articles", "hello")
            assert first.total_count == 1

            # The server has now closed our socket. The next command hits EOF
            # while reading and must not silently resend (post-send failure).
            with pytest.raises(ConnectionError):
                await client.search("articles", "hello")
            assert client.is_connected() is False

            # The following command reconnects transparently.
            third = await client.search("articles", "hello")
            assert third.total_count == 1
            assert server.connections == 2
        finally:
            await client.disconnect()
