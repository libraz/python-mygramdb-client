# Getting Started

This guide will help you get started with the mygramdb-client Python library.

## Installation

### From GitHub

```bash
pip install git+https://github.com/libraz/python-mygramdb-client.git
```

### Using rye

```bash
rye add mygramdb-client --git https://github.com/libraz/python-mygramdb-client.git
```

### From source

```bash
git clone https://github.com/libraz/python-mygramdb-client.git
cd python-mygramdb-client
rye sync
```

> **Note:** PyPI registration is planned for the future.

## Requirements

- Python 3.9 or higher
- asyncio support

## Basic Usage

### Connecting to MygramDB

```python
import asyncio
from mygramdb_client import MygramClient, ClientConfig

async def main():
    # Create client with default configuration
    client = MygramClient()

    # Or with custom configuration
    client = MygramClient(ClientConfig(
        host='localhost',
        port=11016,
        timeout=5.0,
        recv_buffer_size=65536,
        max_query_length=128
    ))

    # Connect to server
    await client.connect()

    # Check connection status
    if client.is_connected():
        print("Connected to MygramDB!")

    # Disconnect when done
    await client.disconnect()

asyncio.run(main())
```

### Searching Documents

```python
from mygramdb_client import MygramClient, SearchOptions

async def search_example():
    client = MygramClient()
    await client.connect()

    # Basic search
    results = await client.search('articles', 'python tutorial')
    print(f"Found {results.total_count} results")

    for result in results.results:
        print(f"  - {result.primary_key}")

    # Search with options
    results = await client.search('articles', 'python', SearchOptions(
        limit=50,
        offset=0,
        and_terms=['tutorial', 'beginner'],
        not_terms=['advanced'],
        filters={'status': 'published'},
        sort_column='created_at',
        sort_desc=True
    ))

    await client.disconnect()
```

### Counting Documents

```python
from mygramdb_client import MygramClient, CountOptions

async def count_example():
    client = MygramClient()
    await client.connect()

    # Basic count
    response = await client.count('articles', 'python')
    print(f"Count: {response.count}")

    # Count with options
    response = await client.count('articles', 'python', CountOptions(
        and_terms=['tutorial'],
        not_terms=['deprecated'],
        filters={'lang': 'en'}
    ))

    await client.disconnect()
```

### Getting a Document by ID

```python
async def get_example():
    client = MygramClient()
    await client.connect()

    doc = await client.get('articles', '12345')
    print(f"Primary Key: {doc.primary_key}")
    print(f"Fields: {doc.fields}")

    await client.disconnect()
```

### Server Information

```python
async def info_example():
    client = MygramClient()
    await client.connect()

    # Get server info
    info = await client.info()
    print(f"Version: {info.version}")
    print(f"Uptime: {info.uptime_seconds} seconds")
    print(f"Documents: {info.doc_count}")
    print(f"Tables: {info.tables}")

    # Get configuration
    config = await client.get_config()
    print(config)

    await client.disconnect()
```

### Replication Control

```python
async def replication_example():
    client = MygramClient()
    await client.connect()

    # Get replication status
    status = await client.get_replication_status()
    print(f"Running: {status.running}")
    print(f"GTID: {status.gtid}")

    # Control replication
    await client.stop_replication()
    await client.start_replication()

    await client.disconnect()
```

### Debug Mode

```python
async def debug_example():
    client = MygramClient()
    await client.connect()

    # Enable debug mode
    await client.enable_debug()

    # Search with debug info
    results = await client.search('articles', 'python')

    if results.debug:
        print(f"Query time: {results.debug.query_time_ms}ms")
        print(f"Candidates: {results.debug.candidates}")
        print(f"Final results: {results.debug.final}")

    # Disable debug mode
    await client.disable_debug()

    await client.disconnect()
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | str | "127.0.0.1" | Server hostname |
| `port` | int | 11016 | Server port |
| `socket_path` | str | "" | Unix socket path; overrides host/port when set |
| `timeout` | float | 5.0 | Default timeout (seconds) for connect and per-command reads |
| `connect_timeout` | Optional[float] | None | Connection deadline; falls back to `timeout` |
| `command_timeout` | Optional[float] | None | Per-response read deadline; falls back to `timeout` |
| `recv_buffer_size` | int | 65536 | Receive buffer size in bytes |
| `max_query_length` | int | 128 | Maximum query expression length |
| `auto_reconnect` | bool | False | Reconnect+resend when the socket died before the write |
| `tcp_keepalive` | bool | True | Enable `SO_KEEPALIVE` on TCP connections |
| `tcp_keepalive_idle` | int | 60 | Idle seconds before the first keepalive probe |

## Error Handling

```python
from mygramdb_client import (
    MygramClient,
    ConnectionError,
    TimeoutError,
    ProtocolError,
    InputValidationError,
    ServerError
)

async def error_handling_example():
    client = MygramClient()

    try:
        await client.connect()
        results = await client.search('articles', 'test')
    except ConnectionError as e:
        print(f"Connection failed: {e}")
    except TimeoutError as e:
        print(f"Operation timed out: {e}")
    except ProtocolError as e:
        print(f"Protocol error: {e}")
    except InputValidationError as e:
        print(f"Invalid input: {e}")
    except ServerError as e:
        print(f"Server error: {e}")
    finally:
        await client.disconnect()
```

## MygramDB v1.8 Notes

Two wire-protocol behaviors matter when targeting a MygramDB v1.8 server:

- **Verbatim boolean transport.** `search_raw()` sends its expression unquoted,
  so the server parses `AND` / `OR` / `NOT` and parenthesized grouping —
  including OR groups nested under AND. Build the expression with
  `convert_search_expression()`; control characters are still rejected before
  the query is sent, so the unquoted transport stays injection-safe.
- **FACET `#` values.** A `facet()` value that starts with `#` is preserved:
  only tab-less `#` lines in the FACET response are treated as comments, so a
  legitimate `#tag`-style value (which carries a tab before its count) is kept.

MygramDB v1.7 (multi-database, `search_raw`, runtime variables, on-demand sync)
and v1.6 (fuzzy search, highlight, facets, BM25) remain supported.

## Next Steps

- [API Reference](api-reference.md) - Complete API documentation
- [Search Expression](search-expression.md) - Advanced search syntax
- [Advanced Usage](advanced-usage.md) - Best practices and patterns
