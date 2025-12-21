# 高度な使い方

このガイドでは、mygramdb-client の高度な使用パターンとベストプラクティスについて説明します。

## コネクションプーリング

高性能なアプリケーションでは、コネクションプーリングを実装して接続を再利用します：

```python
import asyncio
from typing import List, Callable
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

        # 利用可能なクライアントを待機
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


# 使用例
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

## コンテキストマネージャパターン

async コンテキストマネージャを使用してリソースを自動クリーンアップします：

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


# 使用例
async def main():
    async with mygram_client(ClientConfig(host='localhost')) as client:
        results = await client.search('articles', 'python')
        print(f"{results.total_count} 件見つかりました")
    # クライアントは自動的に切断される
```

## バッチ操作

複数のクエリを効率的に処理します：

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


# 使用例
async def main():
    async with mygram_client() as client:
        queries = ['golang', 'python', 'javascript', 'rust']
        results = await batch_search(client, 'articles', queries)

        for query, result in zip(queries, results):
            print(f"クエリ '{query}': {result.total_count} 件")
```

## プールを使った並列処理

コネクションプーリングと並列処理を組み合わせます：

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


# 使用例
results = await parallel_search(pool, 'articles', [
    'golang', 'python', 'javascript', 'rust', 'java', 'c++'
])
```

## ヘルスチェック

監視のためのヘルスチェックを実装します：

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


# 使用例
async def main():
    async with mygram_client() as client:
        health = await health_check(client)
        if health.healthy:
            print("サーバーは正常です")
            print(f"バージョン: {health.version}")
            print(f"稼働時間: {health.uptime} 秒")
        else:
            print(f"サーバーに問題があります: {health.error}")
```

## リトライロジック

一時的な障害に対する自動リトライを実装します：

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
                print(f"試行 {attempt} 失敗、{retry_delay} 秒後にリトライ...")
                await asyncio.sleep(retry_delay)

                # 接続が切れた場合は再接続
                if isinstance(e, ConnectionError) and not client.is_connected():
                    await client.connect()

                continue

            raise

    raise last_error


# 使用例
results = await search_with_retry(client, 'articles', 'test', max_retries=3)
```

## クエリパフォーマンス監視

クエリのパフォーマンスを追跡・分析します：

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

    def reset(self) -> None:
        self.stats.clear()


# 使用例
monitor = PerformanceMonitor()

for _ in range(100):
    await monitor.monitored_search(client, 'articles', 'golang')

stats = monitor.get_stats('golang')
print(f"平均クエリ時間: {stats['avg_ms']:.2f}ms")
print(f"最小: {stats['min_ms']:.2f}ms, 最大: {stats['max_ms']:.2f}ms")
```

## キャッシング層

頻繁にアクセスされるデータのためのキャッシング層を実装します：

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


# 使用例
cached_client = CachedMygramClient(client, ttl_seconds=60.0)

# 最初の呼び出し - サーバーにアクセス
results1 = await cached_client.search('articles', 'golang')

# 2回目の呼び出し - キャッシュから返す
results2 = await cached_client.search('articles', 'golang')

# キャッシュをバイパス
results3 = await cached_client.search('articles', 'golang', use_cache=False)
```

## ページネーションヘルパー

大きな結果セットのページネーションを実装します：

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


# 使用例
paginated = PaginatedSearch(client, 'articles', 'golang', page_size=100)

# ページを順に処理
async for page in paginated.pages():
    print(f"ページには {len(page.results)} 件の結果")
    print(f"全体で {page.total_count} 件")

# すべての結果を一度に取得
all_results = await paginated.get_all_results()
print(f"合計 {len(all_results)} 件取得")
```

## ベストプラクティス

### 1. 本番環境では常にコネクションプーリングを使用する

```python
# 良い例
pool = MygramPool(config, pool_size=10)
await pool.init()

# 悪い例 - リクエストごとに新しい接続を作成
client = MygramClient(config)
await client.connect()
```

### 2. エラーを適切に処理する

```python
# 良い例
try:
    results = await client.search('articles', 'test')
except TimeoutError:
    # リトライロジック
    pass
except ConnectionError:
    # 再接続ロジック
    pass

# 悪い例 - エラー処理なし
results = await client.search('articles', 'test')
```

### 3. 適切なタイムアウトを設定する

```python
# 良い例 - 適切なタイムアウト
client = MygramClient(ClientConfig(timeout=5.0))

# 悪い例 - 短すぎる
client = MygramClient(ClientConfig(timeout=0.1))

# 悪い例 - 長すぎる
client = MygramClient(ClientConfig(timeout=60.0))
```

### 4. パフォーマンスを監視する

```python
# 良い例 - クエリパフォーマンスを追跡
monitor = PerformanceMonitor()
await monitor.monitored_search(client, 'articles', 'test')
```

### 5. リソースを確実にクリーンアップする

```python
# 良い例 - コンテキストマネージャを使用
async with mygram_client() as client:
    await client.search('articles', 'test')

# 良い例 - 明示的なクリーンアップ
client = MygramClient()
try:
    await client.connect()
    # 処理を実行
finally:
    await client.disconnect()

# 悪い例 - 接続リーク
client = MygramClient()
await client.connect()
# 処理を実行
# 切断を忘れる
```
