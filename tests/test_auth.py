"""Administrative authentication over TCP (MygramDB v1.10+).

`AUTH` is bound to the connection, not to the request, so the tests here are
about connection lifecycle: the handshake on connect, its repetition on a
transparent reconnect, and what is left behind when a token is rejected.
"""
import pytest

from mygramdb_client import (
    AuthenticationError,
    ClientConfig,
    ErrorCode,
    MygramClient,
)
from mygramdb_client.errors import InputValidationError

from .fake_server import FakeMygramServer


class TestAuth:
    async def test_configured_token_is_sent_on_connect(self):
        async with FakeMygramServer() as server:
            server.admin_token = "s3cret"
            client = MygramClient(
                ClientConfig(
                    host=server.host, port=server.port, admin_token="s3cret"
                )
            )
            await client.connect()
            try:
                await client.info()
            finally:
                await client.disconnect()

        assert server.commands[0] == "AUTH s3cret"
        assert server.commands[1] == "INFO"

    async def test_no_auth_is_sent_without_a_token(self):
        async with FakeMygramServer() as server:
            client = MygramClient(
                ClientConfig(host=server.host, port=server.port)
            )
            await client.connect()
            try:
                await client.info()
            finally:
                await client.disconnect()

        assert server.commands == ["INFO"]

    async def test_rejected_token_fails_connect_and_drops_the_socket(self):
        async with FakeMygramServer() as server:
            server.admin_token = "s3cret"
            client = MygramClient(
                ClientConfig(
                    host=server.host, port=server.port, admin_token="wrong"
                )
            )
            with pytest.raises(AuthenticationError) as excinfo:
                await client.connect()

        assert excinfo.value.error_code == ErrorCode.PERMISSION_DENIED
        # A half-open, unauthenticated socket must not be left behind.
        assert not client.is_connected()

    async def test_token_with_whitespace_is_quoted(self):
        async with FakeMygramServer() as server:
            server.admin_token = "two words"
            client = MygramClient(
                ClientConfig(
                    host=server.host, port=server.port, admin_token="two words"
                )
            )
            await client.connect()
            try:
                assert client.is_connected()
            finally:
                await client.disconnect()

        assert server.commands[0] == 'AUTH "two words"'

    async def test_reconnect_reauthenticates(self):
        async with FakeMygramServer() as server:
            server.admin_token = "s3cret"
            client = MygramClient(
                ClientConfig(
                    host=server.host,
                    port=server.port,
                    admin_token="s3cret",
                    auto_reconnect=True,
                )
            )
            await client.connect()
            try:
                await client.info()
                # A drop the client has already observed: the next command
                # reconnects, and the reconnect must re-issue AUTH — an
                # unauthenticated connection would silently lose administrative
                # access mid-session.
                await client.disconnect()
                await client.info()
            finally:
                await client.disconnect()

        assert server.connections == 2
        assert server.commands.count("AUTH s3cret") == 2

    async def test_explicit_authenticate_call(self):
        async with FakeMygramServer() as server:
            server.admin_token = "s3cret"
            client = MygramClient(
                ClientConfig(host=server.host, port=server.port)
            )
            await client.connect()
            try:
                await client.authenticate("s3cret")
            finally:
                await client.disconnect()

        assert server.commands[-1] == "AUTH s3cret"

    async def test_explicit_authenticate_rejects_an_empty_token(self):
        client = MygramClient(ClientConfig())
        with pytest.raises(InputValidationError, match="empty"):
            await client.authenticate("")
