"""Type definitions for MygramDB client."""
import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

from .errors import ConnectionError, TimeoutError

_T = TypeVar("_T")


@dataclass
class ClientConfig:
    """Configuration for MygramDB client connection."""

    host: str = "127.0.0.1"
    port: int = 11016
    socket_path: str = ""
    timeout: float = 5.0
    connect_timeout: Optional[float] = None
    """Timeout for establishing a connection. ``None`` falls back to ``timeout``."""

    command_timeout: Optional[float] = None
    """
    Per-read timeout while awaiting a command response. ``None`` falls back to
    ``timeout``. Split from ``connect_timeout`` so a fast connect deadline can
    coexist with a longer allowance for heavy queries.
    """

    recv_buffer_size: int = 65536
    max_query_length: int = 128
    auto_reconnect: bool = False
    """
    Transparently re-establish a dropped connection.

    When enabled, :meth:`MygramClient.send_command` reconnects once and resends
    the command if the socket is found dead *before* the request is written.
    A disconnect that occurs *after* the request was sent is surfaced as a
    :class:`ConnectionError` without resending, since the command may have
    already been applied server-side. Defaults to ``False`` (legacy behavior).
    """

    tcp_keepalive: bool = True
    """
    Enable ``SO_KEEPALIVE`` (and platform keepalive tunables) on TCP
    connections so a silently dropped peer is detected without waiting for the
    next command's read timeout. Ignored for Unix-socket connections.
    """

    tcp_keepalive_idle: int = 60
    """Seconds of idle before the first keepalive probe (platform permitting)."""


@dataclass
class HighlightOptions:
    """
    HIGHLIGHT clause options (MygramDB v1.6+).

    When supplied to ``SearchOptions.highlight``, the server returns
    highlighted snippets in ``SearchResult.snippet``. Pass an empty
    ``HighlightOptions()`` to use server defaults (``<em>``/``</em>``,
    100-codepoint snippet, up to 3 fragments).
    """

    open_tag: str = ""
    """Opening tag for highlighted spans (must be set together with close_tag)."""

    close_tag: str = ""
    """Closing tag for highlighted spans (must be set together with open_tag)."""

    snippet_len: int = 0
    """Snippet length in code points (1..10000); 0 keeps the server default."""

    max_fragments: int = 0
    """Maximum number of fragments per document (1..100); 0 keeps the server default."""


@dataclass
class SearchOptions:
    """Options for search queries."""

    limit: int = 1000
    offset: int = 0
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    sort_column: Optional[str] = None
    """
    Column name for sorting.

    Use the special column name ``_score`` to sort by BM25 relevance
    (MygramDB v1.6+, requires ``verify_text: ascii|all`` on the server).
    Empty or ``None`` sorts by primary key.
    """
    sort_desc: bool = True
    fuzzy: int = 0
    """
    Fuzzy search edit distance (MygramDB v1.6+).

    - 0 (default): exact match
    - 1: allow up to 1 edit (Levenshtein)
    - 2: allow up to 2 edits
    """
    highlight: Optional[HighlightOptions] = None
    """
    HIGHLIGHT clause options (MygramDB v1.6+).

    When set, the server returns matching snippets in
    ``SearchResult.snippet``. Pass ``HighlightOptions()`` to use defaults.
    """


@dataclass
class SearchRawOptions:
    """
    Options for :meth:`MygramClient.search_raw` (MygramDB v1.7+).

    Unlike :class:`SearchOptions`, a raw search sends a pre-built boolean
    expression as a single token, so it exposes only pagination and highlight
    controls — AND/NOT/FILTER refinements belong inside the expression itself.
    """

    limit: int = 0
    """Maximum number of results to return (0 = server default)."""

    offset: int = 0
    """Result offset for pagination."""

    highlight: Optional[HighlightOptions] = None
    """
    HIGHLIGHT clause options. Pass an empty ``HighlightOptions()`` to enable
    highlighting with server defaults.
    """


@dataclass
class CountOptions:
    """Options for count queries."""

    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)


@dataclass
class DebugInfo:
    """Debug information from query execution."""

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


@dataclass
class SearchResult:
    """Individual search result."""

    primary_key: str
    score: Optional[float] = None
    snippet: Optional[str] = None
    """
    Highlighted snippet (HIGHLIGHT clause, MygramDB v1.6+).

    Present only when the search request enabled highlighting via
    ``SearchOptions.highlight``. Empty string when no snippet was produced
    for this document.
    """


@dataclass
class SearchResponse:
    """Response from a search query."""

    results: List[SearchResult]
    total_count: int
    debug: Optional[DebugInfo] = None


@dataclass
class CountResponse:
    """Response from a count query."""

    count: int
    debug: Optional[DebugInfo] = None


@dataclass
class Document:
    """Retrieved document from MygramDB."""

    primary_key: str
    fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class ServerInfo:
    """Server information from INFO command."""

    version: str = ""
    uptime_seconds: int = 0
    total_requests: int = 0
    active_connections: int = 0
    index_size_bytes: int = 0
    doc_count: int = 0
    tables: List[str] = field(default_factory=list)


@dataclass
class ReplicationStatus:
    """MySQL replication status."""

    running: bool = False
    gtid: str = ""
    status_str: str = ""
    processed_events: int = 0
    """Total binlog events processed since startup (multi-line response only)."""

    queue_size: int = 0
    """Pending events in the replication apply queue (multi-line response only)."""


@dataclass
class DumpStatus:
    """Status of a dump operation."""

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


@dataclass
class CacheStats:
    """Cache statistics."""

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


@dataclass
class SimplifiedExpression:
    """Simplified search expression result."""

    main_term: str
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)


@dataclass
class FacetOptions:
    """
    FACET options (MygramDB v1.6+).

    When ``query`` is empty, FACET returns the distinct values across the
    entire table. When ``query`` is provided, the aggregation is scoped to
    the matching documents (with optional AND/NOT/FILTER refinements).
    """

    query: str = ""
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    limit: int = 0
    """Maximum number of facet values to return (0 = no limit)."""


@dataclass
class FacetValue:
    """A single FACET value with its document count (MygramDB v1.6+)."""

    value: str
    count: int


@dataclass
class FacetResponse:
    """FACET response (MygramDB v1.6+)."""

    results: List[FacetValue] = field(default_factory=list)


@dataclass
class RetryPolicy:
    """
    Exponential backoff with full jitter for transient failures.

    Only exceptions in ``retryable`` are retried. Server-side rejections
    (``ServerError``), input errors (``InputValidationError``) and framing
    errors (``ProtocolError``) are not retryable: resending cannot change the
    outcome. Commands with side effects are the caller's responsibility — the
    pool applies this only to its read-only delegation API.
    """

    max_attempts: int = 3
    base_delay: float = 0.05
    max_delay: float = 1.0
    retryable: Tuple[Type[BaseException], ...] = (TimeoutError, ConnectionError)

    def is_retryable(self, exc: BaseException) -> bool:
        return isinstance(exc, self.retryable)

    def delay_for(self, attempt: int) -> float:
        """Full-jitter delay before retry ``attempt`` (1-based)."""
        ceiling = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return random.uniform(0, ceiling)

    async def run(
        self,
        func: Callable[[], Awaitable[_T]],
        on_retry: Optional[Callable[[int, BaseException], None]] = None,
    ) -> _T:
        """
        Invoke ``func`` with retries. ``func`` must be re-callable: it is
        awaited afresh on each attempt. ``on_retry(attempt, exc)`` is invoked
        just before each backoff sleep, if provided.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                return await func()
            except Exception as exc:
                if attempt >= self.max_attempts or not self.is_retryable(exc):
                    raise
                if on_retry is not None:
                    on_retry(attempt, exc)
                await asyncio.sleep(self.delay_for(attempt))


@dataclass
class CircuitBreakerConfig:
    """
    Trip settings for the pool's circuit breaker.

    Consecutive connect/timeout failures up to ``failure_threshold`` open the
    breaker; it stays open for ``reset_timeout`` seconds, then allows a single
    trial (half-open) before closing on success or re-opening on failure.
    """

    failure_threshold: int = 5
    reset_timeout: float = 10.0


class PoolEvent(str, Enum):
    """Observability events emitted by :class:`MygramPool`."""

    ACQUIRE = "acquire"
    """Payload: ``{"wait_seconds": float}`` — a connection was handed out."""

    CONNECTION_DISCARDED = "connection_discarded"
    """A connection was dropped after failing validation or rotation."""

    RETRY = "retry"
    """Payload: ``{"attempt": int, "error": str}`` — a command is being retried."""

    BREAKER_STATE_CHANGE = "breaker_state_change"
    """Payload: ``{"state": str}`` — the circuit breaker changed state."""


@dataclass
class PoolConfig:
    """
    Sizing and wait-control settings for :class:`MygramPool`.

    A pool multiplexes many concurrent requests over several connections, each
    of which still serializes its own commands. The effective concurrency is
    therefore bounded by ``max_connections``.
    """

    min_connections: int = 1
    """Connections opened eagerly by :meth:`MygramPool.open`."""

    max_connections: int = 10
    """Upper bound on live connections (also the concurrency ceiling)."""

    acquire_timeout: Optional[float] = 5.0
    """
    Maximum time to wait for a free connection when the pool is saturated.
    ``None`` waits indefinitely.
    """

    max_pending: int = 0
    """
    Upper bound on callers queued waiting for a connection. When the queue is
    full, :meth:`MygramPool.acquire` fails immediately with
    ``PoolExhaustedError`` instead of waiting. ``0`` means unbounded.
    """

    max_connection_lifetime: float = 0.0
    """
    Recycle a connection once it has been alive this many seconds (checked on
    release and before hand-out). ``0`` disables rotation.
    """

    idle_health_check_interval: float = 30.0
    """
    Validate a connection before hand-out when it has been idle at least this
    many seconds. ``0`` validates on every acquire; a negative value disables
    idle validation.
    """

    retry_policy: Optional[RetryPolicy] = None
    """
    Retry policy applied to the read-only delegation API (``search`` / ``count``
    / ``get`` / ``facet`` / ``info``). ``None`` disables retries.
    """

    circuit_breaker: Optional[CircuitBreakerConfig] = None
    """
    Circuit breaker for the delegation API. Sits outside the retry policy, so
    an open breaker fails fast without retrying. ``None`` disables it.
    """

    on_event: Optional[Callable[["PoolEvent", Dict[str, Any]], None]] = None
    """
    Synchronous callback for pool events (see :class:`PoolEvent`). Exceptions
    raised by the callback are swallowed so instrumentation cannot disrupt the
    pool.
    """


@dataclass
class PoolStats:
    """Point-in-time snapshot of :class:`MygramPool` state."""

    total_connections: int = 0
    """Live connections currently owned by the pool."""

    available: int = 0
    """Idle connections ready to hand out."""

    in_use: int = 0
    """Connections currently checked out by callers."""

    pending_waiters: int = 0
    """Callers blocked waiting for a connection."""

    total_acquires: int = 0
    """Connections successfully handed out over the pool's lifetime."""

    total_acquire_wait_seconds: float = 0.0
    """Cumulative time callers spent waiting for a connection."""

    dead_connections_discarded: int = 0
    """Connections dropped after failing validation or rotation."""

    reconnects: int = 0
    """Replacement connections created to refill after a discard."""
