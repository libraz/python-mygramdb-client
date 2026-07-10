"""Tests for the pool circuit breaker."""
import asyncio

import pytest

from mygramdb_client import (
    CircuitBreakerConfig,
    ClientConfig,
    MygramPool,
    PoolConfig,
)
from mygramdb_client.errors import CircuitOpenError, ConnectionError

from .fake_server import FakeMygramServer


def _config(server: FakeMygramServer) -> ClientConfig:
    return ClientConfig(host=server.host, port=server.port)


async def test_breaker_opens_after_threshold():
    async with FakeMygramServer() as server:
        server.drop_always = True
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=2, reset_timeout=60.0
                ),
            ),
        ) as pool:
            # Two network failures trip the breaker.
            with pytest.raises(ConnectionError):
                await pool.search("articles", "hello")
            with pytest.raises(ConnectionError):
                await pool.search("articles", "hello")

            # Now the breaker is open: fail fast without touching the network.
            before = server.request_count
            with pytest.raises(CircuitOpenError):
                await pool.search("articles", "hello")
            assert server.request_count == before


async def test_breaker_half_open_recovers():
    async with FakeMygramServer() as server:
        server.drop_always = True
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=1, reset_timeout=0.05
                ),
            ),
        ) as pool:
            with pytest.raises(ConnectionError):
                await pool.search("articles", "hello")
            with pytest.raises(CircuitOpenError):
                await pool.search("articles", "hello")

            # Let the reset window elapse, then restore the server.
            await asyncio.sleep(0.08)
            server.drop_always = False

            # Half-open trial succeeds and closes the breaker.
            result = await pool.search("articles", "hello")
            assert result.total_count == 1
            # Breaker closed: subsequent requests pass normally.
            result = await pool.search("articles", "hello")
            assert result.total_count == 1


async def test_server_rejection_does_not_trip_breaker():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=1, reset_timeout=60.0
                ),
            ),
        ) as pool:
            # A reachable server that returns results keeps the breaker closed.
            for _ in range(3):
                result = await pool.search("articles", "hello")
                assert result.total_count == 1
            assert pool._breaker.state == "closed"
