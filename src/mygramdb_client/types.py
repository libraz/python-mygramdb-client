"""Type definitions for MygramDB client."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ClientConfig:
    """Configuration for MygramDB client connection."""

    host: str = "127.0.0.1"
    port: int = 11016
    socket_path: str = ""
    timeout: float = 5.0
    recv_buffer_size: int = 65536
    max_query_length: int = 128


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
