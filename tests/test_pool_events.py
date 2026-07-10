"""Tests for MygramPool observability event hooks."""
from typing import Any, Dict, List, Tuple

from mygramdb_client import (
    CircuitBreakerConfig,
    ClientConfig,
    MygramPool,
    PoolConfig,
    PoolEvent,
    RetryPolicy,
)
from mygramdb_client.errors import ConnectionError

from .fake_server import FakeMygramServer


def _config(server: FakeMygramServer) -> ClientConfig:
    return ClientConfig(host=server.host, port=server.port)


async def test_acquire_event_emitted():
    events: List[Tuple[PoolEvent, Dict[str, Any]]] = []
    async with FakeMygramServer() as server:
        async with MygramPool(
            _config(server),
            PoolConfig(on_event=lambda e, p: events.append((e, p))),
        ) as pool:
            await pool.search("articles", "hello")
    kinds = [e for e, _ in events]
    assert PoolEvent.ACQUIRE in kinds
    acquire_payload = next(p for e, p in events if e == PoolEvent.ACQUIRE)
    assert "wait_seconds" in acquire_payload


async def test_retry_event_emitted():
    events: List[Tuple[PoolEvent, Dict[str, Any]]] = []
    async with FakeMygramServer() as server:
        server.drop_next_request = True
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                retry_policy=RetryPolicy(
                    max_attempts=3, base_delay=0.001, max_delay=0.002
                ),
                on_event=lambda e, p: events.append((e, p)),
            ),
        ) as pool:
            result = await pool.search("articles", "hello")
            assert result.total_count == 1
    retries = [p for e, p in events if e == PoolEvent.RETRY]
    assert len(retries) >= 1
    assert retries[0]["attempt"] == 1
    assert "error" in retries[0]


async def test_breaker_state_change_event_emitted():
    events: List[Tuple[PoolEvent, Dict[str, Any]]] = []
    async with FakeMygramServer() as server:
        server.drop_always = True
        async with MygramPool(
            _config(server),
            PoolConfig(
                min_connections=1,
                max_connections=1,
                idle_health_check_interval=-1,
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=1, reset_timeout=60.0
                ),
                on_event=lambda e, p: events.append((e, p)),
            ),
        ) as pool:
            try:
                await pool.search("articles", "hello")
            except ConnectionError:
                pass
    changes = [p for e, p in events if e == PoolEvent.BREAKER_STATE_CHANGE]
    assert any(c["state"] == "open" for c in changes)


async def test_event_callback_exception_is_swallowed():
    async with FakeMygramServer() as server:
        def boom(event, payload):
            raise RuntimeError("callback blew up")

        async with MygramPool(
            _config(server), PoolConfig(on_event=boom)
        ) as pool:
            # A misbehaving callback must not break the request.
            result = await pool.search("articles", "hello")
            assert result.total_count == 1
