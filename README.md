# mygramdb-client

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python client library for [MygramDB](https://github.com/libraz/mygram-db/) - A high-performance in-memory full-text search engine that is **25-200x faster** than MySQL FULLTEXT with MySQL replication support.

## Features

- **Async/Await API** - Modern asyncio-based interface
- **Full Protocol Support** - All MygramDB commands (SEARCH, COUNT, GET, INFO, etc.)
- **Search Expression Parser** - Web-style search syntax (+required, -excluded, "phrase", OR, grouping)
- **Type Safety** - Full type hints with dataclasses
- **Input Validation** - Built-in protection against control character injection
- **Debug Mode** - Built-in support for query performance metrics

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

## Quick Start

```python
import asyncio
from mygramdb_client import MygramClient, ClientConfig, SearchOptions, simplify_search_expression

async def main():
    # Create client with configuration
    client = MygramClient(ClientConfig(
        host='localhost',
        port=11016
    ))

    await client.connect()

    # Parse web-style search expression (space = AND, - = NOT)
    expr = simplify_search_expression('hello world -spam')
    # expr = SimplifiedExpression(main_term='hello', and_terms=['world'], not_terms=['spam'])

    # Search with AND/NOT terms
    results = await client.search('articles', expr.main_term, SearchOptions(
        and_terms=expr.and_terms,
        not_terms=expr.not_terms,
        limit=100,
        offset=50,  # MySQL-compatible: LIMIT 50,100
        filters={'status': 'published', 'lang': 'en'},
        sort_column='created_at',
        sort_desc=True
    ))

    print(f"Found {results.total_count} results")

    # Count matching documents
    count = await client.count('articles', 'technology')

    # Get document by ID
    doc = await client.get('articles', '12345')

    await client.disconnect()

asyncio.run(main())
```

## Documentation

- **[Getting Started](docs/en/getting-started.md)** - Installation, configuration, and basic usage
- **[API Reference](docs/en/api-reference.md)** - Complete API documentation
- **[Search Expression](docs/en/search-expression.md)** - Advanced search syntax guide
- **[Advanced Usage](docs/en/advanced-usage.md)** - Connection pooling, error handling, and best practices

## Type Hints

The library provides full type hints with dataclasses:

```python
from mygramdb_client import (
    ClientConfig,
    SearchResponse,
    CountResponse,
    Document,
    ServerInfo,
    SearchOptions
)
```

## Development

```bash
# Install dependencies
rye sync

# Run tests
rye run pytest

# Lint
rye run flake8 src tests
```

## License

MIT

## Author

libraz <libraz@libraz.net>

## Links

- [MygramDB](https://github.com/libraz/mygram-db/) - The MygramDB server
- [GitHub](https://github.com/libraz/python-mygramdb-client) - This repository

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
