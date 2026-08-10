"""Tests for MygramPool against a real in-process server."""
import asyncio

import pytest

from mygramdb_client import (
    ClientConfig,
    MygramPool,
    PoolClosedError,
    PoolConfig,
    PoolExhaustedError,
    PoolStats,
    PoolTimeoutError,
)

from .fake_server import FakeMygramServer


def _client_config(server: FakeMygramServer) -> ClientConfig:
    return ClientConfig(host=server.host, port=server.port)


class TestPoolConfig:
    def test_defaults(self):
        cfg = PoolConfig()
        assert cfg.min_connections == 1
        assert cfg.max_connections == 10
        assert cfg.acquire_timeout == 5.0
        assert cfg.max_pending == 0

    def test_validates_sizing(self):
        with pytest.raises(ValueError):
            MygramPool(ClientConfig(), PoolConfig(max_connections=0))
        with pytest.raises(ValueError):
            MygramPool(
                ClientConfig(),
                PoolConfig(min_connections=5, max_connections=2),
            )


async def test_acquire_context_manager():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(min_connections=1, max_connections=2),
        ) as pool:
            async with pool.acquire() as client:
                result = await client.search("articles", "hello")
                assert result.total_count == 1
            stats = pool.stats()
            assert stats.total_connections >= 1
            assert stats.in_use == 0


async def test_delegation_api():
    async with FakeMygramServer() as server:
        async with MygramPool(_client_config(server)) as pool:
            search = await pool.search("articles", "hello")
            assert search.total_count == 1

            count = await pool.count("articles", "hello")
            assert count.count == 1

            doc = await pool.get("articles", "pk1")
            assert doc.primary_key == "pk1"

            info = await pool.info()
            assert info.version == "1.10.0"


async def test_sequential_reuses_min_connections():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(min_connections=2, max_connections=4),
        ) as pool:
            for _ in range(10):
                result = await pool.search("articles", "hello")
                assert result.total_count == 1
            stats = pool.stats()
            # No concurrency, so the pool never grew past its warm set.
            assert stats.total_connections == 2
            assert stats.total_acquires == 10
        assert server.connections == 2


async def test_concurrency_bounded_by_max_connections():
    async with FakeMygramServer(response_delay=0.05) as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(min_connections=0, max_connections=2),
        ) as pool:
            results = await asyncio.gather(
                *[pool.search("articles", "hello") for _ in range(6)]
            )
            assert all(r.total_count == 1 for r in results)
            # The server must never have seen more than max_connections at once.
            assert server.max_active <= 2
            assert server.connections <= 2


async def test_acquire_timeout_raises():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(
                min_connections=1, max_connections=1, acquire_timeout=0.05
            ),
        ) as pool:
            async with pool.acquire():
                with pytest.raises(PoolTimeoutError):
                    async with pool.acquire():
                        pass


async def test_max_pending_raises_immediately():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                max_pending=1,
                acquire_timeout=2.0,
            ),
        ) as pool:
            async def hold_briefly():
                async with pool.acquire():
                    pass

            async with pool.acquire():
                waiter = asyncio.create_task(hold_briefly())
                await asyncio.sleep(0.05)  # let the waiter enqueue
                assert pool.stats().pending_waiters == 1

                with pytest.raises(PoolExhaustedError):
                    async with pool.acquire():
                        pass
            await waiter


async def test_acquire_after_close_raises():
    async with FakeMygramServer() as server:
        pool = MygramPool(_client_config(server))
        await pool.open()
        await pool.close()
        with pytest.raises(PoolClosedError):
            async with pool.acquire():
                pass


async def test_lifetime_rotation_discards_and_refills():
    async with FakeMygramServer() as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(
                min_connections=0,
                max_connections=2,
                max_connection_lifetime=0.01,
                idle_health_check_interval=-1,
            ),
        ) as pool:
            async with pool.acquire() as client:
                await client.search("articles", "hello")
                await asyncio.sleep(0.03)  # exceed the lifetime while checked out
            stats = pool.stats()
            assert stats.dead_connections_discarded >= 1
            assert stats.reconnects >= 1


async def test_stats_snapshot_type():
    async with FakeMygramServer() as server:
        async with MygramPool(_client_config(server)) as pool:
            await pool.search("articles", "hello")
            stats = pool.stats()
            assert isinstance(stats, PoolStats)
            assert stats.total_acquires >= 1
            assert stats.pending_waiters == 0


async def test_close_wakes_blocked_waiter():
    """close() must unblock a waiter parked on an idle connection that will
    never be released, rather than let it hang forever."""
    async with FakeMygramServer() as server:
        pool = MygramPool(
            _client_config(server),
            PoolConfig(
                min_connections=1, max_connections=1, acquire_timeout=None
            ),
        )
        await pool.open()

        holder = pool.acquire()
        await holder.__aenter__()  # occupy the only connection

        async def waiter():
            async with pool.acquire():
                return "acquired"

        blocked = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)  # let it park in _wait_for_idle
        assert pool.stats().pending_waiters == 1

        await asyncio.wait_for(pool.close(), timeout=2.0)

        with pytest.raises(PoolClosedError):
            await asyncio.wait_for(blocked, timeout=2.0)


async def test_high_concurrency_returns_all_connections():
    """Under heavy mixed load the pool never exceeds its ceiling and, once
    quiescent, every connection is back in the idle set (no leak)."""
    async with FakeMygramServer(response_delay=0.005) as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(min_connections=2, max_connections=8, acquire_timeout=5.0),
        ) as pool:
            async def one(i: int) -> None:
                if i % 3 == 0:
                    async with pool.acquire() as client:
                        await client.count("articles", "x")
                else:
                    await pool.search("articles", "hello")

            await asyncio.gather(*[one(i) for i in range(200)])

            stats = pool.stats()
            assert stats.in_use == 0
            assert stats.available == stats.total_connections
            assert stats.total_connections <= 8
            assert stats.total_acquires == 200
            assert server.max_active <= 8
            assert server.connections <= 8


async def test_idle_health_check_recovers_silently_dead_connection():
    """A connection that died while idle is detected on hand-out and replaced,
    transparently, when idle_health_check_interval forces a probe."""
    async with FakeMygramServer() as server:
        async with MygramPool(
            _client_config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=0,  # probe on every acquire
            ),
        ) as pool:
            first = await pool.search("articles", "hello")
            assert first.total_count == 1

            # The peer drops the connection while it sits idle in the pool.
            await asyncio.sleep(0.02)
            assert server.sever_connections() >= 1
            await asyncio.sleep(0.02)

            # Next hand-out probes the now-dead idle connection, discards it,
            # and serves the request on a fresh one.
            second = await pool.search("articles", "hello")
            assert second.total_count == 1
            # A fresh physical connection proves the dead one was not reused.
            assert server.connections >= 2
