"""
Connection pool for MygramDB clients.

A single :class:`MygramClient` owns one connection and serializes every command
on it, so a lone client cannot exceed one in-flight request. :class:`MygramPool`
multiplexes concurrent requests over several clients, validates connections
before hand-out, and transparently replaces ones that have died.
"""
import asyncio
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TypeVar

from .client import MygramClient
from .errors import (
    CircuitOpenError,
    ConnectionError,
    PoolClosedError,
    PoolExhaustedError,
    PoolTimeoutError,
    TimeoutError,
)
from .types import (
    CircuitBreakerConfig,
    ClientConfig,
    CountOptions,
    CountResponse,
    Document,
    FacetOptions,
    FacetResponse,
    PoolConfig,
    PoolEvent,
    PoolStats,
    SearchOptions,
    SearchRawOptions,
    SearchResponse,
    ServerInfo,
)

_T = TypeVar("_T")


def _is_network_failure(exc: Optional[BaseException]) -> bool:
    """
    True for connect/timeout failures that indicate the server is unreachable.
    Pool-control errors (saturation, closed, breaker-open) and server-side
    rejections do not count: the server is still reachable.
    """
    if exc is None:
        return False
    if isinstance(
        exc,
        (PoolTimeoutError, PoolExhaustedError, PoolClosedError, CircuitOpenError),
    ):
        return False
    return isinstance(exc, (ConnectionError, TimeoutError))


class _CircuitBreaker:
    """Three-state breaker: closed -> open -> half-open -> closed/open."""

    def __init__(
        self,
        config: CircuitBreakerConfig,
        on_state_change: Optional[Callable[[str], None]] = None,
    ):
        self._config = config
        self._on_state_change = on_state_change
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_in_flight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def before_request(self) -> None:
        """Raise CircuitOpenError when the breaker forbids a request."""
        async with self._lock:
            if self._state == "open":
                if (time.monotonic() - self._opened_at) >= self._config.reset_timeout:
                    self._set_state("half_open")
                    self._half_open_in_flight = True
                    return
                raise CircuitOpenError("Circuit breaker is open")
            if self._state == "half_open":
                if self._half_open_in_flight:
                    raise CircuitOpenError(
                        "Circuit breaker is half-open; a trial is in progress"
                    )
                self._half_open_in_flight = True
            # closed: allow through

    async def record(self, exc: Optional[BaseException]) -> None:
        failure = _is_network_failure(exc)
        async with self._lock:
            if self._state == "half_open":
                self._half_open_in_flight = False
                if failure:
                    self._open()
                else:
                    self._close()
                return
            if failure:
                self._failures += 1
                if self._failures >= self._config.failure_threshold:
                    self._open()
            else:
                self._failures = 0

    def _open(self) -> None:
        self._opened_at = time.monotonic()
        self._set_state("open")

    def _close(self) -> None:
        self._failures = 0
        self._set_state("closed")

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if self._on_state_change is not None:
            self._on_state_change(state)


class _PooledEntry:
    """A pooled connection plus the timestamps used to age and validate it."""

    __slots__ = ("client", "created_at", "last_used_at")

    def __init__(self, client: MygramClient):
        self.client = client
        now = time.monotonic()
        self.created_at = now
        self.last_used_at = now


class PooledConnection:
    """
    Async context manager yielding a checked-out :class:`MygramClient`.

    Returned by :meth:`MygramPool.acquire`; the connection is returned to the
    pool on exit.
    """

    def __init__(self, pool: "MygramPool"):
        self._pool = pool
        self._entry: Optional[_PooledEntry] = None

    async def __aenter__(self) -> MygramClient:
        self._entry = await self._pool._acquire_entry()
        return self._entry.client

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        entry, self._entry = self._entry, None
        if entry is not None:
            await self._pool._release_entry(entry)


class MygramPool:
    """
    A pool of :class:`MygramClient` connections.

    Example::

        async with MygramPool(ClientConfig(host="localhost")) as pool:
            async with pool.acquire() as client:
                result = await client.search("articles", "hello")

            # or via the delegation API
            result = await pool.search("articles", "hello")
    """

    def __init__(
        self,
        config: Optional[ClientConfig] = None,
        pool_config: Optional[PoolConfig] = None,
    ):
        base = config or ClientConfig()
        # Pooled connections always self-heal: a client that reconnects on its
        # own next command is cheaper than discarding and recreating it.
        self._config = replace(base, auto_reconnect=True)
        self._pool_config = pool_config or PoolConfig()

        if self._pool_config.max_connections < 1:
            raise ValueError("max_connections must be >= 1")
        if self._pool_config.min_connections < 0:
            raise ValueError("min_connections must be >= 0")
        if self._pool_config.min_connections > self._pool_config.max_connections:
            raise ValueError("min_connections must not exceed max_connections")

        self._idle: "asyncio.Queue[_PooledEntry]" = asyncio.Queue()
        self._all: Set[_PooledEntry] = set()
        self._lock = asyncio.Lock()
        self._size = 0
        self._pending_waiters = 0
        self._closed = False
        # Set by close() to wake waiters blocked on an idle connection that
        # will never arrive, so they fail fast instead of hanging.
        self._closing = asyncio.Event()

        self._breaker: Optional[_CircuitBreaker] = None
        if self._pool_config.circuit_breaker is not None:
            self._breaker = _CircuitBreaker(
                self._pool_config.circuit_breaker,
                on_state_change=self._on_breaker_state_change,
            )

        # Stats counters.
        self._total_acquires = 0
        self._total_acquire_wait = 0.0
        self._dead_discarded = 0
        self._reconnects = 0

    # -- events ------------------------------------------------------------

    def _emit(self, event: PoolEvent, payload: Dict[str, Any]) -> None:
        callback = self._pool_config.on_event
        if callback is None:
            return
        try:
            callback(event, payload)
        except Exception:
            # Instrumentation must never disrupt pool operation.
            pass

    def _on_breaker_state_change(self, state: str) -> None:
        self._emit(PoolEvent.BREAKER_STATE_CHANGE, {"state": state})

    # -- lifecycle ---------------------------------------------------------

    async def open(self) -> None:
        """Eagerly open ``min_connections`` connections."""
        if self._closed:
            raise PoolClosedError("Pool is closed")
        entries: List[_PooledEntry] = []
        for _ in range(self._pool_config.min_connections):
            entries.append(await self._create_entry())
        for entry in entries:
            self._idle.put_nowait(entry)

    async def close(self) -> None:
        """Close the pool and disconnect every connection it owns."""
        self._closed = True
        # Wake anyone blocked in _wait_for_idle: no connection will be released
        # back once we start tearing down, so a bare get() would hang forever.
        self._closing.set()
        # Drain idle queue so no stale entries linger.
        while not self._idle.empty():
            try:
                self._idle.get_nowait()
            except asyncio.QueueEmpty:
                break
        async with self._lock:
            entries = list(self._all)
            self._all.clear()
            self._size = 0
        for entry in entries:
            await entry.client.disconnect()

    async def __aenter__(self) -> "MygramPool":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    # -- acquire / release -------------------------------------------------

    def acquire(self) -> PooledConnection:
        """
        Return an async context manager yielding a pooled client::

            async with pool.acquire() as client:
                await client.search(...)
        """
        return PooledConnection(self)

    async def _acquire_entry(self) -> _PooledEntry:
        if self._closed:
            raise PoolClosedError("Pool is closed")

        wait_start = time.monotonic()
        waited = False

        while True:
            entry = self._take_idle_nowait()
            if entry is None:
                entry = await self._maybe_create()
            if entry is None:
                entry = await self._wait_for_idle()
                waited = True

            entry = await self._validate_or_replace(entry)
            if entry is None:
                # Validation discarded a dead connection and could not build a
                # replacement; try again from the top.
                continue

            entry.last_used_at = time.monotonic()
            wait_seconds = (time.monotonic() - wait_start) if waited else 0.0
            async with self._lock:
                self._total_acquires += 1
                self._total_acquire_wait += wait_seconds
            self._emit(PoolEvent.ACQUIRE, {"wait_seconds": wait_seconds})
            return entry

    def _take_idle_nowait(self) -> Optional[_PooledEntry]:
        # Preserve FIFO fairness: never barge ahead of queued waiters.
        if self._pending_waiters > 0:
            return None
        try:
            return self._idle.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def _maybe_create(self) -> Optional[_PooledEntry]:
        async with self._lock:
            if self._closed:
                raise PoolClosedError("Pool is closed")
            if self._size >= self._pool_config.max_connections:
                return None
            self._size += 1
        try:
            return await self._connect_entry()
        except BaseException:
            async with self._lock:
                self._size -= 1
            raise

    async def _wait_for_idle(self) -> _PooledEntry:
        cfg = self._pool_config
        if cfg.max_pending > 0 and self._pending_waiters >= cfg.max_pending:
            raise PoolExhaustedError(
                f"Pool waiter queue is full (max_pending={cfg.max_pending})"
            )
        self._pending_waiters += 1
        # Race the idle wait against a close signal so a concurrent close()
        # unblocks the waiter immediately instead of leaving it stranded on a
        # queue that will never be refilled.
        get_task = asyncio.ensure_future(self._idle.get())
        close_task = asyncio.ensure_future(self._closing.wait())
        try:
            done, _ = await asyncio.wait(
                {get_task, close_task},
                timeout=cfg.acquire_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            self._pending_waiters -= 1
            for task in (get_task, close_task):
                if not task.done():
                    task.cancel()

        if get_task in done and not get_task.cancelled():
            entry = get_task.result()
            if self._closed:
                # Closed as the connection was handed over: drop it and fail.
                await self._discard(entry)
                raise PoolClosedError("Pool is closed")
            return entry
        if self._closed or close_task in done:
            raise PoolClosedError("Pool is closed")
        raise PoolTimeoutError(
            f"Timed out acquiring a connection after {cfg.acquire_timeout}s"
        )

    async def _release_entry(self, entry: _PooledEntry) -> None:
        if self._closed:
            await self._discard(entry)
            return
        if self._is_expired(entry):
            # Rotate: drop the aged connection and refill so a waiter is served.
            await self._discard(entry)
            replacement = await self._safe_create()
            if replacement is not None:
                self._idle.put_nowait(replacement)
            return
        self._idle.put_nowait(entry)

    # -- validation & connection management --------------------------------

    async def _validate_or_replace(
        self, entry: _PooledEntry
    ) -> Optional[_PooledEntry]:
        """
        Return a usable entry, replacing ``entry`` if it is expired or fails a
        health check. Returns ``None`` when the dead entry could not be
        replaced (caller retries).
        """
        if self._is_expired(entry) or not self._is_healthy(entry):
            healthy = await self._check_health(entry)
            if self._is_expired(entry) or not healthy:
                await self._discard(entry)
                return await self._safe_create()
        return entry

    def _is_expired(self, entry: _PooledEntry) -> bool:
        lifetime = self._pool_config.max_connection_lifetime
        if lifetime <= 0:
            return False
        return (time.monotonic() - entry.created_at) >= lifetime

    def _is_healthy(self, entry: _PooledEntry) -> bool:
        """Cheap check: needs a probe only if disconnected or idle too long."""
        if not entry.client.is_connected():
            return False
        interval = self._pool_config.idle_health_check_interval
        if interval < 0:
            return True
        return (time.monotonic() - entry.last_used_at) < interval

    async def _check_health(self, entry: _PooledEntry) -> bool:
        """Probe the connection with a lightweight round-trip."""
        # NOTE: a dedicated PING command is not confirmed to exist server-side;
        # INFO is used as the probe until one is available.
        try:
            await entry.client.info()
            return True
        except Exception:
            return False

    async def _create_entry(self) -> _PooledEntry:
        """Create and register a new connection, bumping the size counter."""
        async with self._lock:
            self._size += 1
        try:
            return await self._connect_entry()
        except BaseException:
            async with self._lock:
                self._size -= 1
            raise

    async def _connect_entry(self) -> _PooledEntry:
        """Open a connection for an already-reserved size slot."""
        client = MygramClient(self._config)
        await client.connect()
        entry = _PooledEntry(client)
        async with self._lock:
            self._all.add(entry)
        return entry

    async def _safe_create(self) -> Optional[_PooledEntry]:
        """Create a replacement connection, counting it as a reconnect."""
        try:
            entry = await self._create_entry()
        except Exception:
            return None
        async with self._lock:
            self._reconnects += 1
        return entry

    async def _discard(self, entry: _PooledEntry) -> None:
        discarded = False
        async with self._lock:
            if entry in self._all:
                self._all.discard(entry)
                self._size -= 1
                self._dead_discarded += 1
                discarded = True
        await entry.client.disconnect()
        if discarded:
            self._emit(PoolEvent.CONNECTION_DISCARDED, {})

    # -- stats -------------------------------------------------------------

    def stats(self) -> PoolStats:
        """Return a point-in-time snapshot of pool state."""
        return PoolStats(
            total_connections=self._size,
            available=self._idle.qsize(),
            in_use=self._size - self._idle.qsize(),
            pending_waiters=self._pending_waiters,
            total_acquires=self._total_acquires,
            total_acquire_wait_seconds=self._total_acquire_wait,
            dead_connections_discarded=self._dead_discarded,
            reconnects=self._reconnects,
        )

    # -- delegation API ----------------------------------------------------

    async def _run(self, func: Callable[[MygramClient], Awaitable[_T]]) -> _T:
        """
        Acquire a connection and run ``func`` on it, applying the pool's
        circuit breaker and retry policy (if any) around the command. The
        breaker sits outside retries, so an open breaker fails fast. The
        connection is held for the whole attempt sequence; a self-healing
        client reconnects between retries so a transient drop is absorbed on
        the same slot.
        """
        if self._breaker is not None:
            await self._breaker.before_request()
        try:
            result = await self._run_inner(func)
        except BaseException as exc:
            if self._breaker is not None:
                await self._breaker.record(exc)
            raise
        if self._breaker is not None:
            await self._breaker.record(None)
        return result

    async def _run_inner(
        self, func: Callable[[MygramClient], Awaitable[_T]]
    ) -> _T:
        async with self.acquire() as client:
            policy = self._pool_config.retry_policy
            if policy is None:
                return await func(client)

            def on_retry(attempt: int, exc: BaseException) -> None:
                self._emit(
                    PoolEvent.RETRY, {"attempt": attempt, "error": str(exc)}
                )

            return await policy.run(lambda: func(client), on_retry=on_retry)

    async def search(
        self,
        table: str,
        query: str,
        options: Optional[SearchOptions] = None,
    ) -> SearchResponse:
        return await self._run(lambda c: c.search(table, query, options))

    async def search_raw(
        self,
        table: str,
        raw_query: str,
        options: Optional[SearchRawOptions] = None,
    ) -> SearchResponse:
        return await self._run(lambda c: c.search_raw(table, raw_query, options))

    async def count(
        self,
        table: str,
        query: str,
        options: Optional[CountOptions] = None,
    ) -> CountResponse:
        return await self._run(lambda c: c.count(table, query, options))

    async def get(self, table: str, primary_key: str) -> Document:
        return await self._run(lambda c: c.get(table, primary_key))

    async def facet(
        self,
        table: str,
        column: str,
        options: Optional[FacetOptions] = None,
    ) -> FacetResponse:
        return await self._run(lambda c: c.facet(table, column, options))

    async def info(self) -> ServerInfo:
        return await self._run(lambda c: c.info())
