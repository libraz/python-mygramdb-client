# API Reference

Complete API documentation for the mygramdb-client Python library.

## MygramClient

The main client class for interacting with MygramDB.

### Constructor

```python
MygramClient(config: Optional[ClientConfig] = None)
```

Creates a new MygramDB client instance.

**Parameters:**
- `config` - Optional client configuration. Uses defaults if not provided.

### Methods

#### connect()

```python
async def connect() -> None
```

Connect to MygramDB server. When `ClientConfig.admin_token` is set, `AUTH` is
issued on the fresh connection before it is handed back (v1.10+).

**Raises:**
- `ConnectionError` - If connection fails
- `TimeoutError` - If connection times out
- `AuthenticationError` - If the configured admin token is rejected

#### authenticate() (v1.10+)

```python
async def authenticate(token: str) -> None
```

Authenticate this connection for administrative commands. Only needed for an
ad-hoc token — setting `ClientConfig.admin_token` authenticates automatically on
connect and on every transparent reconnect, which is what a long-lived client
wants.

**Raises:**
- `AuthenticationError` - If the server rejects the token
- `ProtocolError` - If the reply is not an `AUTH` acknowledgement

#### disconnect()

```python
async def disconnect() -> None
```

Disconnect from server.

#### is_connected()

```python
def is_connected() -> bool
```

Check if connected to server.

**Returns:** `True` if connected, `False` otherwise.

#### search()

```python
async def search(
    table: str,
    query: str,
    options: Optional[SearchOptions] = None
) -> SearchResponse
```

Search for documents in a table. Multi-word queries are quoted automatically so
they reach the server as a single phrase token; use
[`search_raw()`](#search_raw) for boolean `AND`/`OR`/`NOT`/grouping expressions,
or set `options.query_mode = QueryMode.BOOLEAN` (v1.10+) to combine such an
expression with filters, sorting, fuzzy matching and highlighting in one call.

**Parameters:**
- `table` - Table name to search in. In a MygramDB v1.7+ multi-database
  deployment, pass a `database.table` identity (e.g. `app_db.articles`); a bare
  name still works for single-database servers.
- `query` - Search query text, or a boolean expression when
  `options.query_mode` is `QueryMode.BOOLEAN`
- `options` - Optional search options

**Returns:** `SearchResponse` containing results and total count.

**Raises:**
- `ConnectionError` - If not connected
- `TimeoutError` - If operation times out
- `ProtocolError` - If server returns an error
- `InputValidationError` - If input validation fails

`search_with_highlights(table, query, options=None)` is the same call with the
`HIGHLIGHT` clause enabled, returning snippets in `result.snippet`.

#### search_raw()

```python
async def search_raw(
    table: str,
    raw_query: str,
    options: Optional[SearchRawOptions] = None
) -> SearchResponse
```

Search using a pre-built boolean expression (MygramDB v1.7+). The expression is
sent verbatim (unquoted, MygramDB v1.8+) so the server's AST parser sees the
nested `AND` / `OR` / `NOT` / grouping structure; a leading quote would collapse
it into a single phrase. Pair with
[`convert_search_expression()`](#convert_search_expression) to preserve OR /
grouping semantics that `search()`'s AND/NOT decomposition cannot express.
Control characters are rejected before the query is sent, so the unquoted
transport stays injection-safe.

**Parameters:**
- `table` - Table name (bare or `database.table`)
- `raw_query` - Pre-built boolean expression (must not be empty)
- `options` - Optional `SearchRawOptions` (`limit`, `offset`, `highlight`)

**Returns:** `SearchResponse` containing results and total count.

**Example:**
```python
raw = convert_search_expression('python OR (ruby AND rails)')
results = await client.search_raw('articles', raw, SearchRawOptions(limit=50))
```

`search_raw_with_highlights(table, raw_query, options=None)` is the same call
with a `HIGHLIGHT` clause enabled, returning snippets in `result.snippet`.

#### count()

```python
async def count(
    table: str,
    query: str,
    options: Optional[CountOptions] = None
) -> CountResponse
```

Count matching documents in a table.

**Parameters:**
- `table` - Table name to count documents in
- `query` - Search query text
- `options` - Optional count options

**Returns:** `CountResponse` containing count.

#### get()

```python
async def get(table: str, primary_key: str) -> Document
```

Get a document by its primary key.

**Parameters:**
- `table` - Table name
- `primary_key` - Primary key value

**Returns:** `Document` containing primary key and fields.

#### facet() (v1.6+)

```python
async def facet(
    table: str,
    column: str,
    options: Optional[FacetOptions] = None
) -> FacetResponse
```

Aggregate distinct values of a filter column with per-value document counts.
When `options.query` is empty, the whole table is aggregated; when set, the
aggregation is scoped to matching documents (with optional AND/NOT/FILTER
refinements).

**Parameters:**
- `table` - Table name (bare or `database.table`)
- `column` - Filter column to aggregate
- `options` - Optional `FacetOptions` (`query`, `and_terms`, `not_terms`,
  `filters`, `filter_conditions`, `limit`, `offset`)

**Returns:** `FacetResponse` containing the requested page of facet values and,
from v1.9, the total distinct value count in `total_count`.

#### info()

```python
async def info() -> ServerInfo
```

Get server information.

**Returns:** `ServerInfo` with version, uptime, statistics, and — from v1.10 —
`data_initialized` and `ready`.

#### get_config()

```python
async def get_config() -> str
```

Get server configuration in YAML format.

**Returns:** Configuration string.

#### get_replication_status()

```python
async def get_replication_status() -> ReplicationStatus
```

Get current replication status.

**Returns:** `ReplicationStatus` with running state and GTID, plus the v1.10
diagnostics (reported state, CRC errors, schema compatibility, the last failure
and the applied-progress lag).

#### stop_replication()

```python
async def stop_replication() -> None
```

Stop binlog replication.

#### start_replication()

```python
async def start_replication() -> None
```

Start binlog replication.

#### enable_debug()

```python
async def enable_debug() -> None
```

Enable debug mode for this connection.

#### disable_debug()

```python
async def disable_debug() -> None
```

Disable debug mode.

#### send_command()

```python
async def send_command(command: str) -> str
```

Send raw command to server.

**Parameters:**
- `command` - Command string (without CRLF terminator)

**Returns:** Response string from server.

#### set_variable() (v1.7+)

```python
async def set_variable(name: str, value: str) -> None
```

Set a runtime variable (MySQL-compatible `SET`). Values containing whitespace
are quoted automatically. Raises `ProtocolError` if the server rejects it.

#### show_variables() (v1.7+)

```python
async def show_variables(like_pattern: Optional[str] = None) -> str
```

Return the runtime variables table (`SHOW VARIABLES [LIKE <pattern>]`) as the
raw server response string.

#### sync() (v1.7+)

```python
async def sync(table: str) -> str
```

Start an on-demand full reload of a table (`SYNC <table>`). Accepts a bare or
`database.table` identity. Returns the server acknowledgement.

#### sync_status() (v1.7+)

```python
async def sync_status() -> str
```

Return the `SYNC STATUS` report (in-flight and recent sync operations) as the
raw server response string.

#### sync_stop() (v1.7+)

```python
async def sync_stop(table: Optional[str] = None) -> str
```

Stop a running sync. With no table, stops every in-flight sync; with a table,
stops only that table's sync.

#### optimize()

```python
async def optimize(table: Optional[str] = None) -> None
```

Rebuild the index for one table, or every table when `table` is `None`.

#### dump_save()

```python
async def dump_save(filepath: str) -> str
```

Save an index snapshot to a server-side file. Returns the path being written.

#### dump_load()

```python
async def dump_load(filepath: str) -> None
```

Load the index from a server-side dump file.

#### dump_status()

```python
async def dump_status() -> DumpStatus
```

Return the status of an in-flight or recent dump save/load.

**Returns:** `DumpStatus` snapshot.

#### dump_verify()

```python
async def dump_verify(filepath: str) -> str
```

Verify the integrity of a dump file. Returns the raw verification response.

#### dump_info()

```python
async def dump_info(filepath: str) -> str
```

Return metadata about a dump file as the raw server response string.

#### cache_stats()

```python
async def cache_stats() -> CacheStats
```

Return query-cache statistics.

**Returns:** `CacheStats` with hit/miss counters and memory usage.

#### cache_clear()

```python
async def cache_clear(table: Optional[str] = None) -> None
```

Clear the query cache for one table, or all caches when `table` is `None`.

#### cache_enable()

```python
async def cache_enable() -> None
```

Enable the query cache.

#### cache_disable()

```python
async def cache_disable() -> None
```

Disable the query cache.

---

## MygramPool

A pool of `MygramClient` connections for high-throughput workloads. Each pooled
connection still serializes its own commands, so effective concurrency is bounded
by `PoolConfig.max_connections`. Pooled connections always run with
`auto_reconnect` enabled.

### Constructor

```python
MygramPool(
    config: Optional[ClientConfig] = None,
    pool_config: Optional[PoolConfig] = None,
)
```

### Methods

#### open()

```python
async def open() -> None
```

Eagerly open `PoolConfig.min_connections` connections. Also invoked by
`async with pool:`.

#### close()

```python
async def close() -> None
```

Close the pool and disconnect every connection it owns.

#### acquire()

```python
def acquire() -> PooledConnection
```

Return an async context manager that yields a checked-out `MygramClient`; the
connection is returned to the pool on exit.

```python
async with pool.acquire() as client:
    result = await client.search('articles', 'hello')
```

**Raises:**
- `PoolTimeoutError` - If no connection becomes free within `acquire_timeout`
- `PoolExhaustedError` - If the waiter queue is already at `max_pending`
- `PoolClosedError` - If the pool has been closed

#### Delegation API

```python
async def search(table, query, options=None) -> SearchResponse
async def search_raw(table, raw_query, options=None) -> SearchResponse
async def count(table, query, options=None) -> CountResponse
async def get(table, primary_key) -> Document
async def facet(table, column, options=None) -> FacetResponse
async def info() -> ServerInfo
```

Read-only convenience methods that acquire a connection, run the command, and
release it — with `PoolConfig.retry_policy` and `PoolConfig.circuit_breaker`
applied. For anything stateful (replication, sync, `set_variable`), acquire a
connection explicitly with `acquire()`.

#### stats()

```python
def stats() -> PoolStats
```

Return a point-in-time `PoolStats` snapshot.

### PooledConnection

Async context manager returned by `MygramPool.acquire()`. Yields the underlying
`MygramClient` on enter and returns it to the pool on exit.

---

## Types

### ClientConfig

```python
@dataclass
class ClientConfig:
    host: str = "127.0.0.1"
    port: int = 11016
    socket_path: str = ""                     # Unix socket path (overrides host/port when set)
    timeout: float = 5.0                      # Fallback for connect/command timeouts
    connect_timeout: Optional[float] = None   # Connection deadline (None -> timeout)
    command_timeout: Optional[float] = None   # Total response deadline (None -> timeout)
    max_response_bytes: int = 64 * 1024 * 1024  # Cap on one response frame (0 = unbounded)
    admin_token: str = ""                     # Sent as AUTH after connect/reconnect (v1.10+)
    recv_buffer_size: int = 65536
    max_query_length: int = 128
    auto_reconnect: bool = False              # Reconnect+resend if the socket died before the write
    tcp_keepalive: bool = True                # SO_KEEPALIVE on TCP connections
    tcp_keepalive_idle: int = 60              # Idle seconds before the first keepalive probe
```

`auto_reconnect` only resends when the socket is found dead *before* the request
is written; a drop *after* the write is surfaced as `ConnectionError` without
resending, so a possibly-applied command is never silently repeated.

`command_timeout` is one deadline for the whole response, not a timer restarted
by each socket read, so a server that trickles bytes cannot hold a command open
indefinitely. A response that grows past `max_response_bytes` raises
`ProtocolError` and drops the connection — the rest of the oversized frame is
still in flight, so the socket cannot be reused.

`admin_token` is required from v1.10 whenever the server's TCP listener is not
loopback-only. The TCP transport does not encrypt it; keep that listener on a
trusted network or behind a terminating proxy.

### SearchOptions

```python
@dataclass
class SearchOptions:
    limit: int = 1000
    offset: int = 0
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)          # equality filters
    filter_conditions: List[FilterCondition] = field(default_factory=list)  # comparison filters (v1.9+)
    query_mode: QueryMode = QueryMode.LITERAL     # BOOLEAN parses AND/OR/NOT (v1.10+)
    sort_column: Optional[str] = None             # "_score" for BM25 relevance (v1.6+); None = primary key
    sort_desc: bool = True
    fuzzy: int = 0                                # Levenshtein distance 0/1/2 (v1.6+)
    highlight: Optional[HighlightOptions] = None  # enable HIGHLIGHT when set (v1.6+)
```

`filters` are emitted before `filter_conditions`; both use the same wire shape
`FILTER <column> <op> <value>`.

With no `sort_column` the server orders by primary key descending, so only
`sort_desc=False` adds a clause (`SORT ASC`).

### QueryMode (v1.10+)

```python
class QueryMode(str, Enum):
    LITERAL = "literal"   # default: query text is quoted and matched literally
    BOOLEAN = "boolean"   # query text is sent verbatim and parsed as an expression
```

`BOOLEAN` combines a boolean expression with the typed option set (filters,
sorting, fuzzy matching, highlighting) — something `search_raw()` cannot
express. `LITERAL` is the default on every surface, so `alpha AND beta` does not
change meaning when an application moves between TCP, HTTP, and the typed
clients.

### FilterOp (v1.9+)

```python
class FilterOp(str, Enum):
    EQ = "="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
```

### FilterCondition (v1.9+)

```python
@dataclass
class FilterCondition:
    column: str
    value: str
    op: FilterOp = FilterOp.EQ
```

A single comparison filter. `column` is sent unquoted and validated as an
identifier; `value` is quoted when it contains whitespace or quote characters.

### HighlightOptions (v1.6+)

```python
@dataclass
class HighlightOptions:
    open_tag: str = ""       # opening tag; set together with close_tag (server default <em>)
    close_tag: str = ""      # closing tag; set together with open_tag (server default </em>)
    snippet_len: int = 0     # code points per snippet, 1..10000 (0 = server default 100)
    max_fragments: int = 0   # fragments per document, 1..100 (0 = server default 3)
```

An empty `HighlightOptions()` enables highlighting with server defaults.

### SearchRawOptions (v1.7+)

```python
@dataclass
class SearchRawOptions:
    limit: int = 0                              # Max results (0 = server default)
    offset: int = 0                             # Pagination offset
    highlight: Optional[HighlightOptions] = None  # Pass HighlightOptions() for defaults
```

### CountOptions

```python
@dataclass
class CountOptions:
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    filter_conditions: List[FilterCondition] = field(default_factory=list)  # v1.9+
```

### FacetOptions (v1.6+)

```python
@dataclass
class FacetOptions:
    query: str = ""                                      # empty = aggregate the whole table
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    filter_conditions: List[FilterCondition] = field(default_factory=list)  # v1.9+
    limit: int = 0                                       # max facet values (0 = no limit)
    offset: int = 0                                      # distinct values to skip (v1.9+)
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
    snippet: Optional[str] = None   # set only when HIGHLIGHT was requested (v1.6+)
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
    total_count: int = 0   # distinct values before OFFSET/LIMIT (v1.9+)
```

`results` is the returned page; `total_count` is how many distinct values exist
in total. Against a pre-v1.9 server, which reports only the page size,
`total_count` mirrors `len(results)`.

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
    data_initialized: bool = False  # every table finished its initial load (v1.10+)
    ready: bool = False             # ready to serve traffic (v1.10+)
```

`data_initialized` and `ready` come from the same inputs as the HTTP health
endpoint, so a TCP-only deployment can gate traffic without polling HTTP. Both
read `False` against a pre-v1.10 server, which does not report them.

### ReplicationStatus

```python
@dataclass
class ReplicationStatus:
    running: bool = False
    gtid: str = ""
    status_str: str = ""
    processed_events: int = 0  # total binlog events processed (multi-line response)
    queue_size: int = 0        # pending events in the apply queue (multi-line response)

    # Diagnostics (MygramDB v1.10+)
    state: str = ""                # running | stopped | failed | not_configured
    crc_errors: int = 0            # binlog events whose checksum did not verify
    schema_incompatible: bool = False
    last_error_code: int = 0       # from the ErrorCode table; 0 while none is recorded
    last_error: str = ""
    last_applied_unixtime: int = 0
    seconds_since_last_applied: Optional[int] = None
```

`state` separates a reader stopped on request from one stopped on an error,
which `running` alone cannot express; an unrecognized value is passed through
rather than dropped. Fields a pre-v1.10 server does not report keep their
defaults.

`seconds_since_last_applied` is the lag to alert on. It reads `None` when the
server did not report it, and the server itself sends `-1` while no event has
been applied — a sentinel, not a lag of zero. Pair it with
`last_applied_unixtime != 0` to tell a server with no data yet from a genuinely
current replica.

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
    total_queries: int = 0
    invalidation_index_memory_bytes: int = 0
    invalidation_queue_memory_bytes: int = 0
    accounted_memory_bytes: int = 0
    ttl_expirations: int = 0
    rejection_count: int = 0
    rejection_oversize: int = 0
    rejection_memory_budget: int = 0
    rejection_duplicate: int = 0
    stale_entry_removals: int = 0
    decompression_failures: int = 0
    stale_lru_entries: int = 0
    invalidations_immediate: int = 0
    invalidations_deferred: int = 0
    invalidations_batches: int = 0
    avg_cache_hit_time_ms: Optional[float] = None
    avg_cache_miss_time_ms: Optional[float] = None
    total_time_saved_ms: float = 0.0
```

A field the server does not report keeps its default, so the same dataclass
covers an older server's shorter response.

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
    cache_reason: Optional[str] = None
    cache_cost_ms: Optional[float] = None
    cache_key: Optional[str] = None
    highlight: bool = False
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
    min_connections: int = 1                 # Opened eagerly by MygramPool.open()
    max_connections: int = 10                # Upper bound / concurrency ceiling
    acquire_timeout: Optional[float] = 5.0   # Wait cap when saturated (None = forever)
    max_pending: int = 0                     # Waiter-queue cap (0 = unbounded)
    max_connection_lifetime: float = 0.0     # Recycle after N seconds (0 = disabled)
    idle_health_check_interval: float = 30.0 # Validate before hand-out after N idle seconds
    retry_policy: Optional[RetryPolicy] = None            # Applied to the delegation API
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
    retryable: Tuple[Type[BaseException], ...] = (
        TimeoutError, ConnectionError, ServerNotReadyError, ServerBusyError,
    )
```

Exponential backoff with full jitter. Only exceptions in `retryable` are retried.
The two coded server states that can clear on their own — `ServerNotReadyError`
(loading / not ready) and `ServerBusyError` (rate limited, or a long operation
holding the table) — are retried by default, following the server's numeric
error code rather than its message text (v1.10+). A plain `ServerError` (a
request-shape fault), `InputValidationError` and `ProtocolError` are never
retried because resending cannot change the outcome. The pool applies this only
to its read-only delegation API.

### CircuitBreakerConfig

```python
@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5   # Consecutive failures before the breaker opens
    reset_timeout: float = 10.0  # Seconds open before a half-open trial
```

### PoolEvent

```python
class PoolEvent(str, Enum):
    ACQUIRE = "acquire"                          # {"wait_seconds": float}
    CONNECTION_DISCARDED = "connection_discarded"
    RETRY = "retry"                              # {"attempt": int, "error": str}
    BREAKER_STATE_CHANGE = "breaker_state_change"  # {"state": str}
```

Observability events delivered to `PoolConfig.on_event`. The callback is
synchronous and its exceptions are swallowed so instrumentation cannot disrupt
the pool.

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

## Errors

### MygramError

Base exception for all MygramDB errors.

```python
class MygramError(Exception):
    message: str
    code: str
```

### ConnectionError

Raised when connection fails. Also subclasses the builtin `ConnectionError`
(an `OSError`), so `except ConnectionError` catches it whether the caller means
the builtin or this library class.

### ProtocolError

Raised when server returns an invalid response.

### TimeoutError

Raised when an operation times out. Also subclasses the builtin `TimeoutError`;
on Python 3.11+ that is the same class as `asyncio.TimeoutError`, so
`except TimeoutError` (builtin or asyncio) catches it too.

### InputValidationError

Raised when input validation fails. Identifiers (table, primary key, sort
column, filter key) are sent as bare tokens, so they may not contain
whitespace, control characters, or a `"` / `'` / `\` delimiter. Free-form
values (queries, terms, filter values) accept any of those except control
characters and are quoted on the wire as needed.

### ServerError

Raised when server returns an error response.

```python
class ServerError(MygramError):
    message: str
    error_code: Optional[int]   # numeric code from a v1.10+ ERROR frame

    @property
    def is_transient(self) -> bool
```

From v1.10 the server prefixes every `ERROR` frame with a numeric code, and the
client decodes it into `error_code`. Branch on the code rather than matching the
message: messages are free to change, codes are the protocol contract. Against
an older server the frame is untyped and `error_code` is `None`.

`is_transient` is `True` for the codes describing a temporary server state
(`SERVER_LOADING`, `SERVER_NOT_READY`, `SERVER_BUSY`).

### AuthenticationError (v1.10+)

Raised when `AUTH` is rejected, or an administrative command is issued on a
connection that has not authenticated (error code `PERMISSION_DENIED`).
Subclasses `ServerError`.

### ServerNotReadyError (v1.10+)

Raised when the server is still loading or not yet ready to serve the request
(error codes `SERVER_LOADING`, `SERVER_NOT_READY`). Retryable. Subclasses
`ServerError`.

### ServerBusyError (v1.10+)

Raised when the server's request capacity is temporarily exhausted — rate
limiting, or a long-running operation holding the table (error code
`SERVER_BUSY`). Retryable after a backoff. Subclasses `ServerError`.

### ErrorCode (v1.10+)

```python
class ErrorCode(IntEnum):
    ...
```

The server's numeric error codes, grouped by module range: 0-999 general,
1000-1999 configuration, 2000-2999 MySQL/replication, 3000-3999 query parsing,
4000-4999 index/search, 5000-5999 storage/dump, 6000-6999 network/server,
7000-7999 client, 8000-8999 cache.

```python
from mygramdb_client import ErrorCode, ServerError

try:
    await client.search('articles', 'python')
except ServerError as exc:
    if exc.error_code == ErrorCode.TABLE_NOT_FOUND:
        ...
```

`TRANSIENT_ERROR_CODES` is the frozenset backing `ServerError.is_transient`.

### PoolTimeoutError

Raised when acquiring a pooled connection exceeds `PoolConfig.acquire_timeout`.
Subclasses `TimeoutError`, so existing timeout handlers still catch it.

### PoolExhaustedError

Raised when the pool's waiter queue is already at `PoolConfig.max_pending` and a
new `acquire()` would have to wait.

### PoolClosedError

Raised when acquiring from a pool that has already been closed.

### CircuitOpenError

Raised by the pool's delegation API — without touching the network — while the
circuit breaker is open.

---

## Search Expression Functions

### parse_search_expression()

```python
def parse_search_expression(expression: str) -> SearchExpression
```

Parse a web-style search expression.

**Parameters:**
- `expression` - Search expression string

**Returns:** `SearchExpression` with parsed components.

**Raises:** `ValueError` if expression is invalid.

### simplify_search_expression()

```python
def simplify_search_expression(expression: str) -> SimplifiedExpression
```

Simplify a search expression to basic terms.

**Parameters:**
- `expression` - Search expression string

**Returns:** `SimplifiedExpression` with main_term, and_terms, not_terms.

### convert_search_expression()

```python
def convert_search_expression(expression: str) -> str
```

Convert search expression to QueryAST-compatible string.

### has_complex_expression()

```python
def has_complex_expression(expr: SearchExpression) -> bool
```

Check if expression has OR operators or grouping.

### to_query_string()

```python
def to_query_string(expr: SearchExpression) -> str
```

Convert search expression to query string.

---

## Table Identity Helpers (v1.7+)

### qualify_table_identity()

```python
def qualify_table_identity(table: str, database: Optional[str] = None) -> str
```

Build a `database.table` identity (or return the bare table when no database is
given). Both parts are validated and must not contain whitespace, control
characters, or an embedded `.` separator.

```python
qualify_table_identity('articles', 'app_db')  # 'app_db.articles'
```

### parse_table_identity()

```python
def parse_table_identity(identity: str) -> tuple[Optional[str], str]
```

Split a (possibly qualified) identity into `(database, table)`; `database` is
`None` for bare names.

```python
parse_table_identity('app_db.articles')  # ('app_db', 'articles')
parse_table_identity('articles')         # (None, 'articles')
```

---

## Factory Function

### create_mygram_client()

```python
def create_mygram_client(config: Optional[ClientConfig] = None) -> MygramClient
```

Create a new MygramDB client instance.

**Parameters:**
- `config` - Optional client configuration

**Returns:** New `MygramClient` instance.
