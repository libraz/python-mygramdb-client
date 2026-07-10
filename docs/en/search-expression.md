# Search Expression

This guide covers the web-style search expression syntax supported by mygramdb-client.

## Overview

The search expression parser converts web-style search expressions into MygramDB query format. This allows users to use familiar search syntax similar to Google or other search engines.

## Syntax

| Syntax | Description | Example |
|--------|-------------|---------|
| `term` | Optional term | `python` |
| `+term` | Required term (must appear) | `+python` |
| `-term` | Excluded term (must not appear) | `-deprecated` |
| `"phrase"` | Quoted phrase (exact match) | `"machine learning"` |
| `OR` | Logical OR between terms | `python OR ruby` |
| `(expr)` | Grouping | `+(tutorial OR guide)` |

## Examples

### Basic Search

```python
from mygramdb_client import simplify_search_expression

# Single term
expr = simplify_search_expression('python')
# main_term='python', and_terms=[], not_terms=[]

# Multiple terms (implicit AND)
expr = simplify_search_expression('python tutorial')
# main_term='python', and_terms=['tutorial'], not_terms=[]
```

### Required Terms

```python
# Required term with +
expr = simplify_search_expression('+python +tutorial')
# main_term='python', and_terms=['tutorial'], not_terms=[]
```

### Excluded Terms

```python
# Exclude terms with -
expr = simplify_search_expression('python -deprecated -old')
# main_term='python', and_terms=[], not_terms=['deprecated', 'old']
```

### Mixed Terms

```python
# Combine required, optional, and excluded
expr = simplify_search_expression('+python tutorial -deprecated')
# main_term='python', and_terms=['tutorial'], not_terms=['deprecated']
```

### Phrase Search

```python
# Quoted phrase
expr = simplify_search_expression('"machine learning" tutorial')
# main_term='"machine learning"', and_terms=['tutorial'], not_terms=[]

# Required phrase
expr = simplify_search_expression('+"deep learning" -beginner')
# main_term='"deep learning"', and_terms=[], not_terms=['beginner']
```

### Complex Expressions

```python
from mygramdb_client import parse_search_expression, has_complex_expression

# OR expressions
expr = parse_search_expression('python OR ruby')
# has_complex_expression(expr) == True

# Grouped expressions
expr = parse_search_expression('+(tutorial OR guide) python')
# has_complex_expression(expr) == True
```

## Usage with Client

```python
from mygramdb_client import MygramClient, SearchOptions, simplify_search_expression

async def search_with_expression():
    client = MygramClient()
    await client.connect()

    # Parse user input
    user_query = 'golang tutorial -deprecated'
    expr = simplify_search_expression(user_query)

    # Use with search
    results = await client.search('articles', expr.main_term, SearchOptions(
        and_terms=expr.and_terms,
        not_terms=expr.not_terms,
        limit=100
    ))

    print(f"Found {results.total_count} results")
    await client.disconnect()
```

## Full-Width Space Support

The parser normalizes full-width spaces (U+3000) to regular spaces, supporting CJK text input:

```python
# Full-width spaces are treated as regular spaces
expr = simplify_search_expression('日本語　検索')  # U+3000 space
# Same as: simplify_search_expression('日本語 検索')
```

## Error Handling

```python
from mygramdb_client import simplify_search_expression

# Empty expression raises ValueError
try:
    expr = simplify_search_expression('')
except ValueError as e:
    print(f"Error: {e}")  # "Search expression cannot be empty"

# Unterminated quote raises ValueError
try:
    expr = simplify_search_expression('"unterminated')
except ValueError as e:
    print(f"Error: {e}")  # "Unterminated quoted string at position 0"

# Only negative terms raises ValueError
try:
    expr = simplify_search_expression('-spam -deprecated')
except ValueError as e:
    print(f"Error: {e}")  # "Search expression must have at least one positive term"
```

## API Reference

### SearchExpression

```python
@dataclass
class SearchExpression:
    required_terms: List[str] = field(default_factory=list)  # Terms with + prefix
    excluded_terms: List[str] = field(default_factory=list)  # Terms with - prefix
    optional_terms: List[str] = field(default_factory=list)  # Terms without prefix
    raw_expression: str = ""                                 # Original expression (for complex expressions)
```

### SimplifiedExpression

```python
@dataclass
class SimplifiedExpression:
    main_term: str                                    # First positive term
    and_terms: List[str] = field(default_factory=list)  # Additional AND terms
    not_terms: List[str] = field(default_factory=list)  # Excluded terms
```

### Functions

| Function | Description |
|----------|-------------|
| `parse_search_expression(expr)` | Parse to SearchExpression |
| `simplify_search_expression(expr)` | Parse to SimplifiedExpression |
| `convert_search_expression(expr)` | Convert to QueryAST string |
| `has_complex_expression(expr)` | Check for OR/grouping |
| `to_query_string(expr)` | Convert SearchExpression to query string |
