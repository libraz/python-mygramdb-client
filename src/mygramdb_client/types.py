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
class SearchOptions:
    """Options for search queries."""

    limit: int = 1000
    offset: int = 0
    and_terms: List[str] = field(default_factory=list)
    not_terms: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    sort_column: Optional[str] = None
    sort_desc: bool = True


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
