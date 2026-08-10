# Advanced Usage

This guide covers advanced usage patterns and best practices for mygramdb-client.

## Connection Pooling

A single `MygramClient` owns one connection and serializes every command on it,
so a lone client cannot exceed one in-flight request. For high throughput
(hundreds of requests per second), use the built-in `MygramPool`, which
multiplexes concurrent requests over several connections, validates a
connection before hand-out, and transparently replaces one that has died.

```python
from mygramdb_client import MygramClient, MygramPool, ClientConfig, PoolConfig

async def main():
    pool = MygramPool(
        ClientConfig(host='localhost', port=11016),
        PoolConfig(min_connections=2, max_connections=10, acquire_timeout=5.0),
    )
    await pool.open()  # pre-open min_connections
    try:
        # Delegation API: acquire -> run -> release in one call.
        result = await pool.search('articles', 'test')
        print(result.total_count)

        # Or check out a connection explicitly.
        async with pool.acquire() as client:
            result = await client.search('articles', 'test')
            print(result.total_count)

        print(pool.stats())
    finally:
        await pool.close()
```

`MygramPool` is also an async context manager, so `open()`/`close()` can be
handled automatically:

```python
async with MygramPool(ClientConfig(host='localhost')) as pool:
    result = await pool.search('articles', 'test')
```

The effective request concurrency is bounded by `max_connections`. When the
pool is saturated, `acquire()` waits up to `acquire_timeout` and then raises
`PoolTimeoutError`; set `max_pending` to cap the waiter queue and fail fast
with `PoolExhaustedError` instead of queueing without bound.

> Pooled connections are managed with `auto_reconnect` enabled, so a connection
> that drops between uses heals itself on the next command.

From v1.9 the server reaps its own idle connections (`idle_timeout_sec`). The
pool's `idle_health_check_interval` (30s by default) probes a connection that
has been idle at least that long and replaces a reaped one before hand-out, so
keep it below the server's timeout.

## Context Manager Pattern

Use async context manager for automatic resource cleanup:

```python
from contextlib import asynccontextmanager
from mygramdb_client import MygramClient, ClientConfig

@asynccontextmanager
async def mygram_client(config: ClientConfig = None):
    client = MygramClient(config)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


# Usage
async def main():
    async with mygram_client(ClientConfig(host='localhost')) as client:
        results = await client.search('articles', 'python')
        print(f"Found {results.total_count} results")
    # Client is automatically disconnected
```

## Batch Operations

Process multiple queries efficiently:

```python
from typing import List
from mygramdb_client import MygramClient, SearchResponse

async def batch_search(
    client: MygramClient,
    table: str,
    queries: List[str]
) -> List[SearchResponse]:
    return await asyncio.gather(*[
        client.search(table, query) for query in queries
    ])


# Usage
async def main():
    async with mygram_client() as client:
        queries = ['golang', 'python', 'javascript', 'rust']
        results = await batch_search(client, 'articles', queries)

        for query, result in zip(queries, results):
            print(f"Query '{query}': {result.total_count} results")
```

## Parallel Processing with Pool

Fan out concurrent queries; the pool caps concurrency at `max_connections` and
serves each call on its own connection:

```python
async def parallel_search(
    pool: MygramPool,
    table: str,
    queries: List[str]
) -> List[SearchResponse]:
    return await asyncio.gather(*[
        pool.search(table, query) for query in queries
    ])


# Usage
results = await parallel_search(pool, 'articles', [
    'golang', 'python', 'javascript', 'rust', 'java', 'c++'
])
```

## Health Checking

Implement health checks for monitoring:

```python
from dataclasses import dataclass
from typing import Optional
from mygramdb_client import MygramClient

@dataclass
class HealthCheckResult:
    healthy: bool
    version: Optional[str] = None
    uptime: Optional[int] = None
    doc_count: Optional[int] = None
    replication_running: Optional[bool] = None
    error: Optional[str] = None


async def health_check(client: MygramClient) -> HealthCheckResult:
    try:
        info, status = await asyncio.gather(
            client.info(),
            client.get_replication_status()
        )

        return HealthCheckResult(
            healthy=True,
            version=info.version,
            uptime=info.uptime_seconds,
            doc_count=info.doc_count,
            replication_running=status.running
        )
    except Exception as e:
        return HealthCheckResult(
            healthy=False,
            error=str(e)
        )


# Usage
async def main():
    async with mygram_client() as client:
        health = await health_check(client)
        if health.healthy:
            print(f"Server is healthy")
            print(f"Version: {health.version}")
            print(f"Uptime: {health.uptime} seconds")
        else:
            print(f"Server is unhealthy: {health.error}")
```

## Retry Logic

Attach a `RetryPolicy` to the pool to retry transient failures on the pool's
read-only delegation API (`search` / `count` / `get` / `facet` / `info`). It
uses exponential backoff with full jitter and retries connection/timeout errors
plus the two coded server states that can clear on their own —
`ServerNotReadyError` (loading / not ready) and `ServerBusyError` (rate limited,
or a long operation holding the table), both classified from the server's
numeric error code rather than its message text (v1.10+). Other server
rejections (a plain `ServerError`), input errors (`InputValidationError`) and
framing errors (`ProtocolError`) are not retried, since resending cannot change
the outcome.

```python
from mygramdb_client import MygramPool, ClientConfig, PoolConfig, RetryPolicy

pool = MygramPool(
    ClientConfig(host='localhost'),
    PoolConfig(
        max_connections=10,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.05, max_delay=1.0),
    ),
)
await pool.open()

# Retries are applied transparently.
result = await pool.search('articles', 'test')
```

For a bare `MygramClient`, wrap a re-callable coroutine with the same policy:

```python
policy = RetryPolicy(max_attempts=3)
result = await policy.run(lambda: client.search('articles', 'test'))
```

Commands with side effects (`DUMP`, `OPTIMIZE`, `SYNC`, replication control)
are not part of the delegation API and are never retried automatically.

## Circuit Breaker

Under a server outage, retrying every request just piles up connect attempts
and timeouts. Attach a `CircuitBreakerConfig` to the pool to fail fast instead.
After `failure_threshold` consecutive connect/timeout failures the breaker
opens and delegation calls raise `CircuitOpenError` without touching the
network; after `reset_timeout` seconds it allows a single trial and closes
again on success. The breaker sits outside the retry policy, so an open breaker
suppresses retries too. Server rejections (`ServerError`) do not trip it — the
server is still reachable.

```python
from mygramdb_client import (
    MygramPool, ClientConfig, PoolConfig, CircuitBreakerConfig, CircuitOpenError,
)

pool = MygramPool(
    ClientConfig(host='localhost'),
    PoolConfig(
        max_connections=10,
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5, reset_timeout=10.0),
    ),
)
await pool.open()

try:
    result = await pool.search('articles', 'test')
except CircuitOpenError:
    # Serve a degraded response instead of hammering a downed server.
    ...
```

## Observability

Register an `on_event` callback on the pool to feed metrics into any backend
(no dependency on a specific metrics library). Callbacks are synchronous and
their exceptions are swallowed, so instrumentation cannot disrupt the pool.
`pool.stats()` additionally returns a `PoolStats` snapshot.

```python
from mygramdb_client import MygramPool, ClientConfig, PoolConfig, PoolEvent

def on_event(event: PoolEvent, payload: dict) -> None:
    if event is PoolEvent.ACQUIRE:
        record_wait(payload["wait_seconds"])
    elif event is PoolEvent.RETRY:
        count_retry(payload["attempt"])
    elif event is PoolEvent.BREAKER_STATE_CHANGE:
        log_breaker(payload["state"])

pool = MygramPool(ClientConfig(host='localhost'), PoolConfig(on_event=on_event))
await pool.open()

# Snapshot of pool state.
stats = pool.stats()
print(stats.total_connections, stats.in_use, stats.pending_waiters)
```

## Query Performance Monitoring

Track and analyze query performance:

```python
import time
from dataclasses import dataclass
from typing import Dict, Optional
from mygramdb_client import MygramClient, SearchResponse

@dataclass
class QueryStats:
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float('inf')
    max_ms: float = 0.0


class PerformanceMonitor:
    def __init__(self):
        self.stats: Dict[str, QueryStats] = {}

    async def monitored_search(
        self,
        client: MygramClient,
        table: str,
        query: str
    ) -> SearchResponse:
        start_time = time.perf_counter()
        results = await client.search(table, query)
        duration = (time.perf_counter() - start_time) * 1000

        self._record_metric(query, duration)
        return results

    def _record_metric(self, query: str, duration_ms: float) -> None:
        if query not in self.stats:
            self.stats[query] = QueryStats()

        stats = self.stats[query]
        stats.count += 1
        stats.total_ms += duration_ms
        stats.min_ms = min(stats.min_ms, duration_ms)
        stats.max_ms = max(stats.max_ms, duration_ms)

    def get_stats(self, query: str) -> Optional[dict]:
        stats = self.stats.get(query)
        if not stats:
            return None

        return {
            'count': stats.count,
            'avg_ms': stats.total_ms / stats.count,
            'min_ms': stats.min_ms,
            'max_ms': stats.max_ms,
        }

    def get_all_stats(self) -> Dict[str, dict]:
        return {q: self.get_stats(q) for q in self.stats}

    def reset(self) -> None:
        self.stats.clear()


# Usage
monitor = PerformanceMonitor()

for _ in range(100):
    await monitor.monitored_search(client, 'articles', 'golang')

stats = monitor.get_stats('golang')
print(f"Average query time: {stats['avg_ms']:.2f}ms")
print(f"Min: {stats['min_ms']:.2f}ms, Max: {stats['max_ms']:.2f}ms")
```

## Caching Layer

Implement a caching layer for frequently accessed data:

```python
import time
from dataclasses import dataclass
from typing import Dict
from mygramdb_client import MygramClient, SearchResponse

@dataclass
class CacheEntry:
    data: SearchResponse
    timestamp: float


class CachedMygramClient:
    def __init__(self, client: MygramClient, ttl_seconds: float = 60.0):
        self.client = client
        self.ttl = ttl_seconds
        self.cache: Dict[str, CacheEntry] = {}

    async def search(
        self,
        table: str,
        query: str,
        use_cache: bool = True
    ) -> SearchResponse:
        cache_key = f"{table}:{query}"

        if use_cache:
            entry = self.cache.get(cache_key)
            if entry and time.time() - entry.timestamp < self.ttl:
                return entry.data

        results = await self.client.search(table, query)
        self.cache[cache_key] = CacheEntry(data=results, timestamp=time.time())
        return results

    def clear_cache(self) -> None:
        self.cache.clear()

    def get_cache_stats(self) -> dict:
        return {
            'entries': len(self.cache),
        }


# Usage
cached_client = CachedMygramClient(client, ttl_seconds=60.0)

# First call - hits server
results1 = await cached_client.search('articles', 'golang')

# Second call - returns cached result
results2 = await cached_client.search('articles', 'golang')

# Force bypass cache
results3 = await cached_client.search('articles', 'golang', use_cache=False)
```

## Pagination Helper

Implement pagination for large result sets:

```python
from typing import AsyncIterator, List
from mygramdb_client import MygramClient, SearchResponse, SearchResult, SearchOptions

class PaginatedSearch:
    def __init__(
        self,
        client: MygramClient,
        table: str,
        query: str,
        page_size: int = 100
    ):
        self.client = client
        self.table = table
        self.query = query
        self.page_size = page_size

    async def pages(self) -> AsyncIterator[SearchResponse]:
        offset = 0

        while True:
            results = await self.client.search(
                self.table, self.query,
                SearchOptions(limit=self.page_size, offset=offset)
            )

            yield results

            offset += len(results.results)
            if offset >= results.total_count:
                break

    async def get_all_results(self) -> List[SearchResult]:
        all_results = []
        async for page in self.pages():
            all_results.extend(page.results)
        return all_results


# Usage
paginated = PaginatedSearch(client, 'articles', 'golang', page_size=100)

# Iterate through pages
async for page in paginated.pages():
    print(f"Page has {len(page.results)} results")
    print(f"Total available: {page.total_count}")

# Or get all results at once
all_results = await paginated.get_all_results()
print(f"Retrieved {len(all_results)} total results")
```

## Best Practices

### 1. Always Use Connection Pooling in Production

```python
# Good
pool = MygramPool(config, PoolConfig(max_connections=10))
await pool.open()

# Bad - a single client serializes every request onto one connection
client = MygramClient(config)
await client.connect()
```

### 2. Handle Errors Gracefully

```python
# Good
try:
    results = await client.search('articles', 'test')
except TimeoutError:
    # Retry logic
    pass
except ConnectionError:
    # Reconnect logic
    pass

# Bad - no error handling
results = await client.search('articles', 'test')
```

`ConnectionError` and `TimeoutError` also subclass the builtin
`ConnectionError` / `TimeoutError` (both `OSError`), so the handlers above catch
them whether you import the library names or use the builtins. On Python 3.11+,
`except asyncio.TimeoutError` catches `TimeoutError` as well.

Branch on the server's numeric error code rather than its message (v1.10+) —
messages are free to change, codes are the protocol contract:

```python
from mygramdb_client import (
    ErrorCode, ServerError, ServerBusyError, ServerNotReadyError,
)

try:
    results = await client.search('articles', 'test')
except (ServerNotReadyError, ServerBusyError):
    # Temporary server state; the same request may succeed later.
    pass
except ServerError as exc:
    if exc.error_code == ErrorCode.TABLE_NOT_FOUND:
        ...          # a configuration problem, not something to retry
    raise
```

Against a pre-v1.10 server the frame is untyped and `error_code` is `None`, so
keep a fallback path if you must support both.

### 3. Use Appropriate Timeouts

```python
# Good - reasonable timeout
client = MygramClient(ClientConfig(timeout=5.0))

# Bad - too short
client = MygramClient(ClientConfig(timeout=0.1))

# Bad - too long
client = MygramClient(ClientConfig(timeout=60.0))
```

Split the connect deadline from the per-command deadline when a fast connect
must coexist with heavier queries:

```python
# Fail a connect attempt quickly, but allow a heavy query more time.
client = MygramClient(ClientConfig(connect_timeout=0.5, command_timeout=10.0))
```

`command_timeout` bounds the whole response, not each socket read, so a server
that trickles bytes cannot hold a command open past the deadline.

### 4. Set the Admin Token Once (v1.10+)

A MygramDB v1.10 server whose TCP listener is not loopback-only rejects
administrative commands until the connection has authenticated. Put the token on
the config rather than calling `authenticate()` by hand — the config path also
re-authenticates after a transparent reconnect, so a dropped connection does not
silently lose administrative access mid-session:

```python
config = ClientConfig(host='localhost', admin_token='...', auto_reconnect=True)
async with MygramClient(config) as client:
    await client.optimize('articles')
```

### 5. Monitor Performance

```python
# Good - track query performance
monitor = PerformanceMonitor()
await monitor.monitored_search(client, 'articles', 'test')
```

### 6. Clean Up Resources

```python
# Good - use context manager
async with mygram_client() as client:
    await client.search('articles', 'test')

# Good - explicit cleanup
client = MygramClient()
try:
    await client.connect()
    # Do work
finally:
    await client.disconnect()

# Bad - connection leak
client = MygramClient()
await client.connect()
# Do work
# Forget to disconnect
```
