"""Helpers for asserting on the command a client puts on the wire.

Two capture styles, because command construction has two things worth
checking and they need different amounts of machinery:

- :func:`capture_command` drives a real socket against
  :class:`~tests.fake_server.FakeMygramServer`, so what it returns is what the
  server actually received. Use it when the wire form itself is the assertion.
- :func:`run_capturing` swaps out ``send_command`` and never opens a socket,
  so it can also feed a canned response back into the client's parser. Use it
  when a test needs both the request and the parsed reply.
"""
import asyncio
from typing import Awaitable, Callable, List, Tuple

from mygramdb_client import ClientConfig, MygramClient

from .fake_server import FakeMygramServer


async def capture_command(
    issue: Callable[[MygramClient], Awaitable[object]]
) -> str:
    """Run ``issue(client)`` against a fake server and return the command sent."""
    async with FakeMygramServer() as server:
        client = MygramClient(ClientConfig(host=server.host, port=server.port))
        await client.connect()
        try:
            await issue(client)
        finally:
            await client.disconnect()
        return server.commands[-1]


def run_capturing(coro_factory, response="OK RESULTS 0") -> Tuple[List[str], object]:
    """
    Drive a client coroutine while capturing the raw command sent.

    ``response`` may be a string (returned for every call) or a callable taking
    the command and returning the canned response.

    Returns a tuple ``(commands, result)`` where ``commands`` is the list of
    captured command strings and ``result`` is the coroutine's return value.
    """
    client = MygramClient()
    commands: List[str] = []

    async def capture(command):
        commands.append(command)
        if callable(response):
            return response(command)
        return response

    client._connected = True
    client.send_command = capture  # type: ignore[assignment]

    result = asyncio.run(coro_factory(client))
    return commands, result


def unreachable_client() -> MygramClient:
    """
    A client whose ``send_command`` fails the test if it is ever reached.

    For validation tests: the point is that the client rejects the input
    before anything is written to the wire.
    """
    client = MygramClient()
    client._connected = True

    async def capture(command):  # pragma: no cover - must not be reached
        raise AssertionError("send_command should not be called")

    client.send_command = capture  # type: ignore[assignment]
    return client
