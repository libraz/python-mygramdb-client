# 高度な使い方

このガイドでは、mygramdb-client の高度な使用パターンとベストプラクティスについて説明します。

## コネクションプーリング

`MygramClient` は 1 本の接続を持ち、その上で全コマンドを直列化するため、単一クライアントでは同時に 1 リクエストしか処理できません。秒間数百リクエスト規模の高負荷では、組み込みの `MygramPool` を使います。複数接続へリクエストを分散し、貸出前に接続を検証し、死んだ接続を透過的に作り直します。

```python
from mygramdb_client import MygramClient, MygramPool, ClientConfig, PoolConfig

async def main():
    pool = MygramPool(
        ClientConfig(host='localhost', port=11016),
        PoolConfig(min_connections=2, max_connections=10, acquire_timeout=5.0),
    )
    await pool.open()  # min_connections を事前接続
    try:
        # 委譲 API: acquire -> 実行 -> release を 1 呼び出しで行う
        result = await pool.search('articles', 'test')
        print(result.total_count)

        # 明示的に接続を借りることもできる
        async with pool.acquire() as client:
            result = await client.search('articles', 'test')
            print(result.total_count)

        print(pool.stats())
    finally:
        await pool.close()
```

`MygramPool` は async context manager でもあるため、`open()` / `close()` を自動化できます。

```python
async with MygramPool(ClientConfig(host='localhost')) as pool:
    result = await pool.search('articles', 'test')
```

実効的な同時実行数は `max_connections` が上限になります。プールが飽和すると `acquire()` は `acquire_timeout` まで待機し、超過すると `PoolTimeoutError` を送出します。`max_pending` を設定すると待ち行列に上限を設け、無制限に待たせる代わりに `PoolExhaustedError` で即座に失敗させられます。

> プール管理下の接続は `auto_reconnect` が有効な状態で扱われるため、使用の合間に切れた接続は次のコマンドで自己修復します。

v1.9 以降、サーバーはアイドル接続を自ら回収します（`idle_timeout_sec`）。プールの `idle_health_check_interval`（既定 30 秒）はその時間以上アイドルだった接続を払い出し前にプローブし、回収済みなら差し替えるため、サーバー側のタイムアウトより短く設定してください。

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

複数クエリを並行して投げます。プールは同時実行数を `max_connections` に制限し、各呼び出しを個別の接続で処理します。

```python
async def parallel_search(
    pool: MygramPool,
    table: str,
    queries: List[str]
) -> List[SearchResponse]:
    return await asyncio.gather(*[
        pool.search(table, query) for query in queries
    ])


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

`RetryPolicy` をプールに渡すと、読み取り系の委譲 API（`search` / `count` / `get` / `facet` / `info`）に自動リトライが適用されます。指数バックオフ + full jitter で待機し、リトライ対象は接続・タイムアウト系のエラーに加えて、時間が経てば解消しうる 2 つのサーバー状態、すなわち `ServerNotReadyError`（ロード中／未準備）と `ServerBusyError`（レート制限、または長時間動作がテーブルを保持中）です。どちらもメッセージ文字列ではなくサーバーが返す数値エラーコードから判定します（v1.10+）。それ以外のサーバー拒否（素の `ServerError`）、入力不正の `InputValidationError`、フレーミング不整合の `ProtocolError` は再送しても結果が変わらないためリトライしません。

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

# リトライは透過的に適用される
result = await pool.search('articles', 'test')
```

素の `MygramClient` では、再呼び出し可能なコルーチンを同じポリシーで包みます。

```python
policy = RetryPolicy(max_attempts=3)
result = await policy.run(lambda: client.search('articles', 'test'))
```

副作用を伴うコマンド（`DUMP` / `OPTIMIZE` / `SYNC` / レプリケーション制御）は委譲 API に含まれず、自動リトライの対象になりません。

## サーキットブレーカー

サーバー障害中にすべてのリクエストをリトライすると、接続試行とタイムアウトが積み上がるだけです。`CircuitBreakerConfig` をプールに渡すと、代わりに即座に失敗させられます。連続する接続・タイムアウト失敗が `failure_threshold` に達するとブレーカーが open になり、委譲 API はネットワークに触れず `CircuitOpenError` を送出します。`reset_timeout` 秒後に 1 件だけ試行を通し、成功すれば close に戻ります。ブレーカーはリトライポリシーの外側にあるため、open 中はリトライも抑制されます。サーバーが応答した上での拒否（`ServerError`）は「到達可能」とみなし、ブレーカーを開きません。

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
    # ダウン中のサーバーを叩き続けず、縮退したレスポンスを返す
    ...
```

## 観測性

プールに `on_event` コールバックを登録すると、任意のバックエンドへメトリクスを流せます（特定のメトリクスライブラリには依存しません）。コールバックは同期関数で、例外は握りつぶされるため、計測がプール動作を妨げることはありません。加えて `pool.stats()` で `PoolStats` スナップショットを取得できます。

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

# プール状態のスナップショット
stats = pool.stats()
print(stats.total_connections, stats.in_use, stats.pending_waiters)
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

    def get_all_stats(self) -> Dict[str, dict]:
        return {q: self.get_stats(q) for q in self.stats}

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

    def get_cache_stats(self) -> dict:
        return {
            'entries': len(self.cache),
        }


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
pool = MygramPool(config, PoolConfig(max_connections=10))
await pool.open()

# 悪い例 - 単一クライアントは全リクエストを 1 本の接続で直列化する
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

`ConnectionError` と `TimeoutError` は組み込みの `ConnectionError` /
`TimeoutError`（いずれも `OSError`）も継承しているため、ライブラリ名を
インポートしても組み込みを使っても、上記のハンドラで捕捉できます。
Python 3.11+ では `except asyncio.TimeoutError` でも `TimeoutError` を捕捉できます。

分岐はメッセージ文字列ではなくサーバーの数値エラーコードで行ってください（v1.10+）。メッセージは変わりうるものですが、コードはプロトコルの契約です。

```python
from mygramdb_client import (
    ErrorCode, ServerError, ServerBusyError, ServerNotReadyError,
)

try:
    results = await client.search('articles', 'test')
except (ServerNotReadyError, ServerBusyError):
    # 一時的なサーバー状態。同じリクエストが後で成功しうる
    pass
except ServerError as exc:
    if exc.error_code == ErrorCode.TABLE_NOT_FOUND:
        ...          # 設定の問題であり、リトライで解決するものではない
    raise
```

v1.10 未満のサーバーではフレームにコードがなく `error_code` は `None` になるため、両方をサポートする必要があるならフォールバック経路を残してください。

### 3. 適切なタイムアウトを設定する

```python
# 良い例 - 適切なタイムアウト
client = MygramClient(ClientConfig(timeout=5.0))

# 悪い例 - 短すぎる
client = MygramClient(ClientConfig(timeout=0.1))

# 悪い例 - 長すぎる
client = MygramClient(ClientConfig(timeout=60.0))
```

接続確立は速く打ち切りたいが重いクエリには猶予を与えたい場合、接続用とコマンド用のタイムアウトを分離できます。

```python
# 接続失敗は素早く打ち切り、重いクエリには時間を与える
client = MygramClient(ClientConfig(connect_timeout=0.5, command_timeout=10.0))
```

`command_timeout` はソケット読み取りごとではなくレスポンス全体を対象とするため、少しずつバイトを流し続けるサーバーがデッドラインを超えてコマンドを保持することはありません。

### 4. 管理トークンは設定に一度だけ書く（v1.10+）

TCP リスナーがループバック限定でない MygramDB v1.10 サーバーは、認証済みの接続でなければ管理コマンドを拒否します。`authenticate()` を手で呼ぶのではなく、設定にトークンを持たせてください。設定経由なら透過的な再接続後にも再認証されるため、接続が切れてもセッション途中で管理権限を失いません。

```python
config = ClientConfig(host='localhost', admin_token='...', auto_reconnect=True)
async with MygramClient(config) as client:
    await client.optimize('articles')
```

### 5. パフォーマンスを監視する

```python
# 良い例 - クエリパフォーマンスを追跡
monitor = PerformanceMonitor()
await monitor.monitored_search(client, 'articles', 'test')
```

### 6. リソースを確実にクリーンアップする

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
