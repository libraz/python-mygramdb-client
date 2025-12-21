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

テーブル内のドキュメントを検索します。

**パラメータ:**
- `table` - 検索対象のテーブル名
- `query` - 検索クエリ文字列
- `options` - オプションの検索オプション

**戻り値:** 結果と総数を含む `SearchResponse`。

**例外:**
- `ConnectionError` - 未接続の場合
- `TimeoutError` - 操作がタイムアウトした場合
- `ProtocolError` - サーバーがエラーを返した場合
- `InputValidationError` - 入力バリデーションに失敗した場合

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

---

## 型

### ClientConfig

```python
@dataclass
class ClientConfig:
    host: str = "127.0.0.1"
    port: int = 11016
    timeout: float = 5.0
    recv_buffer_size: int = 65536
    max_query_length: int = 128
```

### SearchOptions

```python
@dataclass
class SearchOptions:
    limit: int = 1000
    offset: int = 0
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    sort_column: Optional[str] = None
    sort_desc: bool = True
```

### CountOptions

```python
@dataclass
class CountOptions:
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
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
```

### CountResponse

```python
@dataclass
class CountResponse:
    count: int
    debug: Optional[DebugInfo] = None
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

接続に失敗した場合に発生します。

### ProtocolError

サーバーが不正なレスポンスを返した場合に発生します。

### TimeoutError

操作がタイムアウトした場合に発生します。

### InputValidationError

入力バリデーションに失敗した場合に発生します。

### ServerError

サーバーがエラーレスポンスを返した場合に発生します。

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

## ファクトリ関数

### create_mygram_client()

```python
def create_mygram_client(config: Optional[ClientConfig] = None) -> MygramClient
```

新しい MygramDB クライアントインスタンスを作成します。

**パラメータ:**
- `config` - オプションのクライアント設定

**戻り値:** 新しい `MygramClient` インスタンス。
