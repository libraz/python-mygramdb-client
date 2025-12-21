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

Connect to MygramDB server.

**Raises:**
- `ConnectionError` - If connection fails
- `TimeoutError` - If connection times out

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

Search for documents in a table.

**Parameters:**
- `table` - Table name to search in
- `query` - Search query text
- `options` - Optional search options

**Returns:** `SearchResponse` containing results and total count.

**Raises:**
- `ConnectionError` - If not connected
- `TimeoutError` - If operation times out
- `ProtocolError` - If server returns an error
- `InputValidationError` - If input validation fails

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

#### info()

```python
async def info() -> ServerInfo
```

Get server information.

**Returns:** `ServerInfo` with version, uptime, statistics.

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

**Returns:** `ReplicationStatus` with running state and GTID.

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

---

## Types

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

## Errors

### MygramError

Base exception for all MygramDB errors.

```python
class MygramError(Exception):
    message: str
    code: str
```

### ConnectionError

Raised when connection fails.

### ProtocolError

Raised when server returns an invalid response.

### TimeoutError

Raised when an operation times out.

### InputValidationError

Raised when input validation fails.

### ServerError

Raised when server returns an error response.

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

## Factory Function

### create_mygram_client()

```python
def create_mygram_client(config: Optional[ClientConfig] = None) -> MygramClient
```

Create a new MygramDB client instance.

**Parameters:**
- `config` - Optional client configuration

**Returns:** New `MygramClient` instance.
