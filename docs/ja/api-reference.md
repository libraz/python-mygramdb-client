# API リファレンス

mygramdb-client Python ライブラリの完全な API ドキュメントです。

## MygramClient

MygramDB とやり取りするためのメインクライアントクラスです。

### コンストラクタ

```python
MygramClient(config: Optional[ClientConfig] = None)
```

新しい MygramDB クライアントインスタンスを作成します。

**パラメータ:**
- `config` - オプションのクライアント設定。指定しない場合はデフォルト値を使用。

### メソッド

#### connect()

```python
async def connect() -> None
```

MygramDB サーバーに接続します。

**例外:**
- `ConnectionError` - 接続に失敗した場合
- `TimeoutError` - 接続がタイムアウトした場合

#### disconnect()

```python
async def disconnect() -> None
```

サーバーから切断します。

#### is_connected()

```python
def is_connected() -> bool
```

サーバーへの接続状態を確認します。

**戻り値:** 接続中なら `True`、そうでなければ `False`。

#### search()

```python
async def search(
    table: str,
    query: str,
    options: Optional[SearchOptions] = None
) -> SearchResponse
```

テーブル内のドキュメントを検索します。複数語のクエリは自動的に引用符で囲まれ、
単一のフレーズトークンとしてサーバーに送信されます。`AND`/`OR`/`NOT`/グループ化を
含むブール式には [`search_raw()`](#search_raw) を使用してください。

**パラメータ:**
- `table` - 検索対象のテーブル名。MygramDB v1.7+ のマルチデータベース構成では
  `database.table` 形式の識別子（例: `app_db.articles`）を渡します。単一
  データベースのサーバーでは従来どおりテーブル名のみでも動作します。
- `query` - 検索クエリ文字列
- `options` - オプションの検索オプション

**戻り値:** 結果と総数を含む `SearchResponse`。

**例外:**
- `ConnectionError` - 未接続の場合
- `TimeoutError` - 操作がタイムアウトした場合
- `ProtocolError` - サーバーがエラーを返した場合
- `InputValidationError` - 入力バリデーションに失敗した場合

`search_with_highlights(table, query, options=None)` は同じ呼び出しに `HIGHLIGHT`
句を有効化したもので、スニペットを `result.snippet` で返します。

#### search_raw()

```python
async def search_raw(
    table: str,
    raw_query: str,
    options: Optional[SearchRawOptions] = None
) -> SearchResponse
```

事前に構築したブール式で検索します（MygramDB v1.7+）。式はそのまま（引用符
なし、MygramDB v1.8+）送信されるため、サーバーの AST パーサがネストした
`AND` / `OR` / `NOT` / グループ化の構造を解釈できます。引用符で囲むと式全体が
単一のフレーズに潰れてしまいます。`search()` の AND/NOT 分解では表現できない
OR / グループ化セマンティクスを保持するには、[`convert_search_expression()`](#convert_search_expression)
と組み合わせて使用します。制御文字は送信前に拒否されるため、引用符なしの送信でも
インジェクションに対して安全です。

**パラメータ:**
- `table` - テーブル名（`database.table` 形式も可）
- `raw_query` - 事前構築したブール式（空文字列は不可）
- `options` - オプションの `SearchRawOptions`（`limit`、`offset`、`highlight`）

**戻り値:** 結果と総数を含む `SearchResponse`。

**例:**
```python
raw = convert_search_expression('python OR (ruby AND rails)')
results = await client.search_raw('articles', raw, SearchRawOptions(limit=50))
```

`search_raw_with_highlights(table, raw_query, options=None)` は同じ呼び出しに
`HIGHLIGHT` 句を有効化したものです。

#### count()

```python
async def count(
    table: str,
    query: str,
    options: Optional[CountOptions] = None
) -> CountResponse
```

テーブル内でマッチするドキュメントをカウントします。

**パラメータ:**
- `table` - カウント対象のテーブル名
- `query` - 検索クエリ文字列
- `options` - オプションのカウントオプション

**戻り値:** カウントを含む `CountResponse`。

#### get()

```python
async def get(table: str, primary_key: str) -> Document
```

プライマリキーでドキュメントを取得します。

**パラメータ:**
- `table` - テーブル名
- `primary_key` - プライマリキー値

**戻り値:** プライマリキーとフィールドを含む `Document`。

#### facet() (v1.6+)

```python
async def facet(
    table: str,
    column: str,
    options: Optional[FacetOptions] = None
) -> FacetResponse
```

フィルタ列の distinct な値を、値ごとのドキュメント数とともに集計します。
`options.query` が空の場合はテーブル全体を集計し、指定した場合はマッチする
ドキュメント（オプションの AND/NOT/FILTER による絞り込みを含む）に集計を
スコープします。

**パラメータ:**
- `table` - テーブル名（`database.table` 形式も可）
- `column` - 集計対象のフィルタ列
- `options` - オプションの `FacetOptions`（`query`、`and_terms`、`not_terms`、
  `filters`、`limit`）

**戻り値:** ファセット値とカウントを含む `FacetResponse`。

#### info()

```python
async def info() -> ServerInfo
```

サーバー情報を取得します。

**戻り値:** バージョン、稼働時間、統計情報を含む `ServerInfo`。

#### get_config()

```python
async def get_config() -> str
```

YAML 形式のサーバー設定を取得します。

**戻り値:** 設定文字列。

#### get_replication_status()

```python
async def get_replication_status() -> ReplicationStatus
```

現在のレプリケーション状態を取得します。

**戻り値:** 実行状態と GTID を含む `ReplicationStatus`。

#### stop_replication()

```python
async def stop_replication() -> None
```

binlog レプリケーションを停止します。

#### start_replication()

```python
async def start_replication() -> None
```

binlog レプリケーションを開始します。

#### enable_debug()

```python
async def enable_debug() -> None
```

この接続のデバッグモードを有効にします。

#### disable_debug()

```python
async def disable_debug() -> None
```

デバッグモードを無効にします。

#### send_command()

```python
async def send_command(command: str) -> str
```

サーバーに生のコマンドを送信します。

**パラメータ:**
- `command` - コマンド文字列（CRLF 終端なし）

**戻り値:** サーバーからのレスポンス文字列。

#### set_variable() (v1.7+)

```python
async def set_variable(name: str, value: str) -> None
```

ランタイム変数を設定します（MySQL 互換の `SET`）。空白を含む値は自動的に引用符で
囲まれます。サーバーが拒否した場合は `ProtocolError` を送出します。

#### show_variables() (v1.7+)

```python
async def show_variables(like_pattern: Optional[str] = None) -> str
```

ランタイム変数の一覧（`SHOW VARIABLES [LIKE <pattern>]`）を生のレスポンス文字列
として返します。

#### sync() (v1.7+)

```python
async def sync(table: str) -> str
```

テーブルのオンデマンド完全リロード（`SYNC <table>`）を開始します。テーブル名は
`database.table` 形式も可。サーバーの受理応答を返します。

#### sync_status() (v1.7+)

```python
async def sync_status() -> str
```

`SYNC STATUS` レポート（実行中および直近の同期操作）を生のレスポンス文字列として
返します。

#### sync_stop() (v1.7+)

```python
async def sync_stop(table: Optional[str] = None) -> str
```

実行中の同期を停止します。テーブルを指定しない場合はすべての実行中の同期を、
指定した場合はそのテーブルの同期のみを停止します。

#### optimize()

```python
async def optimize(table: Optional[str] = None) -> None
```

1 つのテーブル、または `table` が `None` の場合はすべてのテーブルのインデックスを
再構築します。

#### dump_save()

```python
async def dump_save(filepath: str) -> str
```

インデックスのスナップショットをサーバー側のファイルに保存します。書き込み先の
パスを返します。

#### dump_load()

```python
async def dump_load(filepath: str) -> None
```

サーバー側のダンプファイルからインデックスをロードします。

#### dump_status()

```python
async def dump_status() -> DumpStatus
```

実行中または直近のダンプの保存／ロードの状態を返します。

**戻り値:** `DumpStatus` スナップショット。

#### dump_verify()

```python
async def dump_verify(filepath: str) -> str
```

ダンプファイルの整合性を検証します。生の検証レスポンスを返します。

#### dump_info()

```python
async def dump_info(filepath: str) -> str
```

ダンプファイルのメタデータを生のレスポンス文字列として返します。

#### cache_stats()

```python
async def cache_stats() -> CacheStats
```

クエリキャッシュの統計情報を返します。

**戻り値:** ヒット／ミスのカウンタとメモリ使用量を含む `CacheStats`。

#### cache_clear()

```python
async def cache_clear(table: Optional[str] = None) -> None
```

1 つのテーブル、または `table` が `None` の場合はすべてのクエリキャッシュを
クリアします。

#### cache_enable()

```python
async def cache_enable() -> None
```

クエリキャッシュを有効にします。

#### cache_disable()

```python
async def cache_disable() -> None
```

クエリキャッシュを無効にします。

---

## MygramPool

高スループット用途向けの `MygramClient` 接続プールです。プール内の各接続は
自身のコマンドを引き続き直列化するため、実効的な同時実行数は
`PoolConfig.max_connections` で制限されます。プール接続では常に
`auto_reconnect` が有効になります。

### コンストラクタ

```python
MygramPool(
    config: Optional[ClientConfig] = None,
    pool_config: Optional[PoolConfig] = None,
)
```

### メソッド

#### open()

```python
async def open() -> None
```

`PoolConfig.min_connections` 個の接続を事前に開きます。`async with pool:` から
も呼び出されます。

#### close()

```python
async def close() -> None
```

プールをクローズし、所有するすべての接続を切断します。

#### acquire()

```python
def acquire() -> PooledConnection
```

チェックアウトした `MygramClient` を返す非同期コンテキストマネージャを返します。
接続は終了時にプールへ返却されます。

```python
async with pool.acquire() as client:
    result = await client.search('articles', 'hello')
```

**発生する例外:**
- `PoolTimeoutError` - `acquire_timeout` 内に接続が空かなかった場合
- `PoolExhaustedError` - 待機キューがすでに `max_pending` に達している場合
- `PoolClosedError` - プールがクローズされている場合

#### 委譲 API

```python
async def search(table, query, options=None) -> SearchResponse
async def search_raw(table, raw_query, options=None) -> SearchResponse
async def count(table, query, options=None) -> CountResponse
async def get(table, primary_key) -> Document
async def facet(table, column, options=None) -> FacetResponse
async def info() -> ServerInfo
```

接続を取得し、コマンドを実行し、返却する読み取り専用の便利メソッドです。
`PoolConfig.retry_policy` と `PoolConfig.circuit_breaker` が適用されます。
状態を伴う操作（レプリケーション、同期、`set_variable` など）には
`acquire()` で明示的に接続を取得してください。

#### stats()

```python
def stats() -> PoolStats
```

その時点の `PoolStats` スナップショットを返します。

### PooledConnection

`MygramPool.acquire()` が返す非同期コンテキストマネージャです。開始時に内部の
`MygramClient` を返し、終了時にプールへ返却します。

---

## 型

### ClientConfig

```python
@dataclass
class ClientConfig:
    host: str = "127.0.0.1"
    port: int = 11016
    socket_path: str = ""                     # Unix ソケットパス（指定時は host/port より優先）
    timeout: float = 5.0                      # connect/command タイムアウトのフォールバック
    connect_timeout: Optional[float] = None   # 接続のデッドライン（None なら timeout）
    command_timeout: Optional[float] = None   # レスポンス読み取りのデッドライン（None なら timeout）
    recv_buffer_size: int = 65536
    max_query_length: int = 128
    auto_reconnect: bool = False              # 書き込み前に切断を検出したら再接続＋再送
    tcp_keepalive: bool = True                # TCP 接続で SO_KEEPALIVE を有効化
    tcp_keepalive_idle: int = 60              # 最初のキープアライブ探索までのアイドル秒数
```

`auto_reconnect` はリクエストの書き込み *前* に切断を検出した場合のみ再送します。
書き込み *後* の切断は再送せずに `ConnectionError` として通知するため、すでに
適用された可能性のあるコマンドが暗黙的に繰り返されることはありません。

### SearchOptions

```python
@dataclass
class SearchOptions:
    limit: int = 1000
    offset: int = 0
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    sort_column: Optional[str] = None             # BM25 相関には "_score"（v1.6+）。None はプライマリキー
    sort_desc: bool = True
    fuzzy: int = 0                                # レーベンシュタイン距離 0/1/2（v1.6+）
    highlight: Optional[HighlightOptions] = None  # 設定時に HIGHLIGHT を有効化（v1.6+）
```

### HighlightOptions (v1.6+)

```python
@dataclass
class HighlightOptions:
    open_tag: str = ""       # 開始タグ。close_tag と一緒に設定（サーバー既定 <em>）
    close_tag: str = ""      # 終了タグ。open_tag と一緒に設定（サーバー既定 </em>）
    snippet_len: int = 0     # スニペットあたりのコードポイント数、1..10000（0 = サーバー既定 100）
    max_fragments: int = 0   # ドキュメントあたりのフラグメント数、1..100（0 = サーバー既定 3）
```

空の `HighlightOptions()` はサーバー既定値でハイライトを有効化します。

### SearchRawOptions (v1.7+)

```python
@dataclass
class SearchRawOptions:
    limit: int = 0                              # 最大結果数（0 = サーバー既定）
    offset: int = 0                             # ページネーションのオフセット
    highlight: Optional[HighlightOptions] = None  # HighlightOptions() で既定値を有効化
```

### CountOptions

```python
@dataclass
class CountOptions:
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
```

### FacetOptions (v1.6+)

```python
@dataclass
class FacetOptions:
    query: str = ""                                      # 空ならテーブル全体を集計
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    limit: int = 0                                       # ファセット値の最大数（0 は無制限）
```

### SearchResponse

```python
@dataclass
class SearchResponse:
    results: List[SearchResult]
    total_count: int
    debug: Optional[DebugInfo] = None
```

### SearchResult

```python
@dataclass
class SearchResult:
    primary_key: str
    score: Optional[float] = None
    snippet: Optional[str] = None   # HIGHLIGHT を要求したときのみ設定（v1.6+）
```

### CountResponse

```python
@dataclass
class CountResponse:
    count: int
    debug: Optional[DebugInfo] = None
```

### FacetValue (v1.6+)

```python
@dataclass
class FacetValue:
    value: str
    count: int
```

### FacetResponse (v1.6+)

```python
@dataclass
class FacetResponse:
    results: List[FacetValue] = field(default_factory=list)
```

### Document

```python
@dataclass
class Document:
    primary_key: str
    fields: Dict[str, str] = field(default_factory=dict)
```

### ServerInfo

```python
@dataclass
class ServerInfo:
    version: str = ""
    uptime_seconds: int = 0
    total_requests: int = 0
    active_connections: int = 0
    index_size_bytes: int = 0
    doc_count: int = 0
    tables: List[str] = field(default_factory=list)
```

### ReplicationStatus

```python
@dataclass
class ReplicationStatus:
    running: bool = False
    gtid: str = ""
    status_str: str = ""
    processed_events: int = 0  # 処理済み binlog イベント総数（複数行レスポンス時）
    queue_size: int = 0        # 適用キュー内の保留イベント数（複数行レスポンス時）
```

### DumpStatus

```python
@dataclass
class DumpStatus:
    status: str = ""
    filepath: str = ""
    tables_total: int = 0
    tables_processed: int = 0
    current_table: str = ""
    elapsed_seconds: float = 0.0
    save_in_progress: bool = False
    load_in_progress: bool = False
    result_filepath: str = ""
    error: str = ""
```

### CacheStats

```python
@dataclass
class CacheStats:
    enabled: bool = False
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    current_entries: int = 0
    memory_bytes: int = 0
    evictions: int = 0
    max_memory_mb: float = 0.0
    current_memory_mb: float = 0.0
    ttl_seconds: int = 0
```

### DebugInfo

```python
@dataclass
class DebugInfo:
    query_time_ms: float = 0.0
    index_time_ms: float = 0.0
    filter_time_ms: float = 0.0
    terms: int = 0
    ngrams: int = 0
    candidates: int = 0
    after_intersection: int = 0
    after_not: int = 0
    after_filters: int = 0
    final: int = 0
    optimization: str = ""
    sort: Optional[str] = None
    cache: Optional[str] = None
    cache_age_ms: Optional[float] = None
    cache_saved_ms: Optional[float] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
```

### SimplifiedExpression

```python
@dataclass
class SimplifiedExpression:
    main_term: str
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
```

### PoolConfig

```python
@dataclass
class PoolConfig:
    min_connections: int = 1                 # MygramPool.open() で事前に開く数
    max_connections: int = 10                # 接続数の上限／同時実行の上限
    acquire_timeout: Optional[float] = 5.0   # 飽和時の待機上限（None は無制限）
    max_pending: int = 0                     # 待機キューの上限（0 は無制限）
    max_connection_lifetime: float = 0.0     # N 秒後に接続を再生成（0 で無効）
    idle_health_check_interval: float = 30.0 # N 秒アイドル後、払い出し前に検証
    retry_policy: Optional[RetryPolicy] = None            # 委譲 API に適用
    circuit_breaker: Optional[CircuitBreakerConfig] = None
    on_event: Optional[Callable[[PoolEvent, Dict[str, Any]], None]] = None
```

### RetryPolicy

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.05
    max_delay: float = 1.0
    retryable: Tuple[Type[BaseException], ...] = (TimeoutError, ConnectionError)
```

フルジッター付きの指数バックオフです。`retryable` に含まれる例外のみリトライ
され、`ServerError` / `InputValidationError` / `ProtocolError` は再送しても結果が
変わらないためリトライされません。プールでは読み取り専用の委譲 API にのみ
適用されます。

### CircuitBreakerConfig

```python
@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5   # ブレーカーが開くまでの連続失敗回数
    reset_timeout: float = 10.0  # ハーフオープン試行までのオープン秒数
```

### PoolEvent

```python
class PoolEvent(str, Enum):
    ACQUIRE = "acquire"                          # {"wait_seconds": float}
    CONNECTION_DISCARDED = "connection_discarded"
    RETRY = "retry"                              # {"attempt": int, "error": str}
    BREAKER_STATE_CHANGE = "breaker_state_change"  # {"state": str}
```

`PoolConfig.on_event` に配信される観測イベントです。コールバックは同期的で、
その例外は握りつぶされるため、計装がプールの動作を妨げることはありません。

### PoolStats

```python
@dataclass
class PoolStats:
    total_connections: int = 0
    available: int = 0
    in_use: int = 0
    pending_waiters: int = 0
    total_acquires: int = 0
    total_acquire_wait_seconds: float = 0.0
    dead_connections_discarded: int = 0
    reconnects: int = 0
```

---

## エラー

### MygramError

すべての MygramDB エラーの基底例外です。

```python
class MygramError(Exception):
    message: str
    code: str
```

### ConnectionError

接続に失敗した場合に発生します。組み込みの `ConnectionError`（`OSError` の
サブクラス）も継承しているため、呼び出し側が組み込みとこのライブラリの
どちらのつもりでも `except ConnectionError` で捕捉できます。

### ProtocolError

サーバーが不正なレスポンスを返した場合に発生します。

### TimeoutError

操作がタイムアウトした場合に発生します。組み込みの `TimeoutError` も継承して
います。Python 3.11+ では `asyncio.TimeoutError` と同一クラスのため、
`except TimeoutError`（組み込み・asyncio いずれも）で捕捉できます。

### InputValidationError

入力バリデーションに失敗した場合に発生します。

### ServerError

サーバーがエラーレスポンスを返した場合に発生します。

### PoolTimeoutError

プール接続の取得が `PoolConfig.acquire_timeout` を超えた場合に発生します。
`TimeoutError` を継承しているため、既存のタイムアウトハンドラでも捕捉できます。

### PoolExhaustedError

プールの待機キューがすでに `PoolConfig.max_pending` に達しており、新たな
`acquire()` が待機を要する場合に発生します。

### PoolClosedError

すでにクローズされたプールから取得しようとした場合に発生します。

### CircuitOpenError

サーキットブレーカーがオープン中に、プールの委譲 API がネットワークに触れずに
発生させます。

---

## 検索式関数

### parse_search_expression()

```python
def parse_search_expression(expression: str) -> SearchExpression
```

Web スタイルの検索式をパースします。

**パラメータ:**
- `expression` - 検索式文字列

**戻り値:** パースされた要素を含む `SearchExpression`。

**例外:** 式が不正な場合は `ValueError`。

### simplify_search_expression()

```python
def simplify_search_expression(expression: str) -> SimplifiedExpression
```

検索式を基本的なタームに簡略化します。

**パラメータ:**
- `expression` - 検索式文字列

**戻り値:** main_term、and_terms、not_terms を含む `SimplifiedExpression`。

### convert_search_expression()

```python
def convert_search_expression(expression: str) -> str
```

検索式を QueryAST 互換の文字列に変換します。

### has_complex_expression()

```python
def has_complex_expression(expr: SearchExpression) -> bool
```

式に OR 演算子やグループ化が含まれるかチェックします。

### to_query_string()

```python
def to_query_string(expr: SearchExpression) -> str
```

SearchExpression をクエリ文字列に変換します。

---

## テーブル識別子ヘルパー (v1.7+)

### qualify_table_identity()

```python
def qualify_table_identity(table: str, database: Optional[str] = None) -> str
```

`database.table` 形式の識別子を構築します（データベースを指定しない場合は
テーブル名のみを返します）。両方の部分はバリデーションされ、空白・制御文字・
埋め込みの `.` 区切り文字を含むことはできません。

```python
qualify_table_identity('articles', 'app_db')  # 'app_db.articles'
```

### parse_table_identity()

```python
def parse_table_identity(identity: str) -> tuple[Optional[str], str]
```

（修飾されている可能性のある）識別子を `(database, table)` に分割します。
テーブル名のみの場合 `database` は `None` になります。

```python
parse_table_identity('app_db.articles')  # ('app_db', 'articles')
parse_table_identity('articles')         # (None, 'articles')
```

---

## ファクトリ関数

### create_mygram_client()

```python
def create_mygram_client(config: Optional[ClientConfig] = None) -> MygramClient
```

新しい MygramDB クライアントインスタンスを作成します。

**パラメータ:**
- `config` - オプションのクライアント設定

**戻り値:** 新しい `MygramClient` インスタンス。
