# Advanced Usage

This guide covers advanced usage patterns and best practices for mygramdb-client.

## Connection Pooling

For high-performance applications, implement connection pooling to reuse connections:

```python
import asyncio
from typing import List, Callable, Awaitable
from mygramdb_client import MygramClient, ClientConfig

class MygramPool:
    def __init__(self, config: ClientConfig, pool_size: int = 10):
        self.config = config
        self.pool_size = pool_size
        self.clients: List[MygramClient] = []
        self.available: List[MygramClient] = []
        self.pending: List[Callable[[MygramClient], None]] = []
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        for _ in range(self.pool_size):
            client = MygramClient(self.config)
            await client.connect()
            self.clients.append(client)
            self.available.append(client)

    async def acquire(self) -> MygramClient:
        async with self._lock:
            if self.available:
                return self.available.pop()

        # Wait for a client to become available
        future: asyncio.Future[MygramClient] = asyncio.Future()
        self.pending.append(lambda c: future.set_result(c))
        return await future

    async def release(self, client: MygramClient) -> None:
        async with self._lock:
            if self.pending:
                callback = self.pending.pop(0)
                callback(client)
            else:
                self.available.append(client)

    async def close(self) -> None:
        for client in self.clients:
            await client.disconnect()
        self.clients.clear()
        self.available.clear()

    def get_stats(self) -> dict:
        return {
            'total': len(self.clients),
            'available': len(self.available),
            'in_use': len(self.clients) - len(self.available),
            'pending': len(self.pending),
        }


# Usage
async def main():
    pool = MygramPool(
        ClientConfig(host='localhost', port=11016),
        pool_size=10
    )
    await pool.init()

    client = await pool.acquire()
    try:
        results = await client.search('articles', 'test')
        print(results)
    finally:
        await pool.release(client)

    print(pool.get_stats())
    await pool.close()
```

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

Combine connection pooling with parallel processing:

```python
async def parallel_search(
    pool: MygramPool,
    table: str,
    queries: List[str]
) -> List[SearchResponse]:
    async def search_one(query: str) -> SearchResponse:
        client = await pool.acquire()
        try:
            return await client.search(table, query)
        finally:
            await pool.release(client)

    return await asyncio.gather(*[search_one(q) for q in queries])


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

Implement automatic retry for transient failures:

```python
import asyncio
from mygramdb_client import (
    MygramClient,
    SearchResponse,
    TimeoutError,
    ConnectionError
)

async def search_with_retry(
    client: MygramClient,
    table: str,
    query: str,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> SearchResponse:
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            return await client.search(table, query)
        except (TimeoutError, ConnectionError) as e:
            last_error = e

            if attempt < max_retries:
                print(f"Attempt {attempt} failed, retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)

                # Reconnect if connection was lost
                if isinstance(e, ConnectionError) and not client.is_connected():
                    await client.connect()

                continue

            raise

    raise last_error


# Usage
results = await search_with_retry(client, 'articles', 'test', max_retries=3)
```

## Query Performance Monitoring

Track and analyze query performance:

```python
import time
from dataclasses import dataclass, field
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
from typing import Dict, Optional
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
from mygramdb_client import MygramClient, SearchResponse, SearchResult

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
            from mygramdb_client import SearchOptions
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
pool = MygramPool(config, pool_size=10)
await pool.init()

# Bad - creates new connection for each request
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

### 3. Use Appropriate Timeouts

```python
# Good - reasonable timeout
client = MygramClient(ClientConfig(timeout=5.0))

# Bad - too short
client = MygramClient(ClientConfig(timeout=0.1))

# Bad - too long
client = MygramClient(ClientConfig(timeout=60.0))
```

### 4. Monitor Performance

```python
# Good - track query performance
monitor = PerformanceMonitor()
await monitor.monitored_search(client, 'articles', 'test')
```

### 5. Clean Up Resources

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
