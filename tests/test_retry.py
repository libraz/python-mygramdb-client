"""Tests for RetryPolicy and its integration with the pool delegation API."""
import pytest

from mygramdb_client import (
    ClientConfig,
    MygramPool,
    PoolConfig,
    RetryPolicy,
)
from mygramdb_client.errors import (
    ConnectionError,
    InputValidationError,
    ProtocolError,
    ServerError,
    TimeoutError,
)

from .fake_server import FakeMygramServer


class TestRetryPolicy:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.is_retryable(TimeoutError("x"))
        assert policy.is_retryable(ConnectionError("x"))

    def test_non_retryable_classification(self):
        policy = RetryPolicy()
        assert not policy.is_retryable(ServerError("x"))
        assert not policy.is_retryable(InputValidationError("x"))
        assert not policy.is_retryable(ProtocolError("x"))

    def test_delay_within_bounds(self):
        policy = RetryPolicy(base_delay=0.1, max_delay=0.4)
        for attempt in range(1, 6):
            delay = policy.delay_for(attempt)
            assert 0.0 <= delay <= 0.4

    async def test_run_retries_then_succeeds(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("transient")
            return "ok"

        policy = RetryPolicy(max_attempts=3, base_delay=0.001, max_delay=0.002)
        assert await policy.run(flaky) == "ok"
        assert calls["n"] == 3

    async def test_run_gives_up_and_reraises(self):
        policy = RetryPolicy(max_attempts=2, base_delay=0.001, max_delay=0.002)

        async def always_fail():
            raise TimeoutError("nope")

        with pytest.raises(TimeoutError):
            await policy.run(always_fail)

    async def test_run_does_not_retry_non_retryable(self):
        calls = {"n": 0}

        async def bad_input():
            calls["n"] += 1
            raise ServerError("rejected")

        policy = RetryPolicy(max_attempts=5, base_delay=0.001)
        with pytest.raises(ServerError):
            await policy.run(bad_input)
        assert calls["n"] == 1


def _config(server: FakeMygramServer) -> ClientConfig:
    return ClientConfig(host=server.host, port=server.port)


async def test_pool_retries_transient_drop():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                retry_policy=RetryPolicy(
                    max_attempts=3, base_delay=0.001, max_delay=0.002
                ),
            ),
        ) as pool:
            # First attempt is dropped mid-flight; the self-healing client
            # reconnects and the retry succeeds.
            server.drop_next_request = True
            result = await pool.search("articles", "hello")
            assert result.total_count == 1


async def test_pool_without_retry_propagates_drop():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
            ),
        ) as pool:
            server.drop_next_request = True
            with pytest.raises(ConnectionError):
                await pool.search("articles", "hello")


async def test_pool_retry_exhaustion_raises():
    async with FakeMygramServer() as server:
        server.drop_always = True
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                retry_policy=RetryPolicy(
                    max_attempts=2, base_delay=0.001, max_delay=0.002
                ),
            ),
        ) as pool:
            with pytest.raises(ConnectionError):
                await pool.search("articles", "hello")


def _slow_config(server: FakeMygramServer) -> ClientConfig:
    return ClientConfig(host=server.host, port=server.port, command_timeout=0.05)


async def test_pool_retries_read_timeout():
    """A read timeout is retryable; the healed connection resends and succeeds."""
    async with FakeMygramServer() as server:
        server.delay_next_request = 0.3
        async with MygramPool(
            _slow_config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                retry_policy=RetryPolicy(
                    max_attempts=3, base_delay=0.001, max_delay=0.002
                ),
            ),
        ) as pool:
            result = await pool.search("articles", "hello")
            assert result.total_count == 1


async def test_pool_replaces_connection_after_read_timeout():
    """Without retries, a timed-out connection must be discarded, not reused:
    reusing it would read the server's late reply as the next response."""
    async with FakeMygramServer() as server:
        server.delay_next_request = 0.3
        async with MygramPool(
            _slow_config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
            ),
        ) as pool:
            with pytest.raises(TimeoutError):
                await pool.search("articles", "hello")

            result = await pool.search("articles", "hello")
            assert result.total_count == 1
            assert result.results[0].primary_key == "pk1"
            # A second physical connection proves the poisoned one was replaced.
            assert server.connections == 2
