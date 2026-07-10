# 検索式

このガイドでは、mygramdb-client がサポートする Web スタイルの検索式構文について説明します。

## 概要

検索式パーサーは、Web スタイルの検索式を MygramDB のクエリ形式に変換します。これにより、Google などの検索エンジンと同様の馴染みのある検索構文を使用できます。

## 構文

| 構文 | 説明 | 例 |
|------|------|-----|
| `term` | オプションのターム | `python` |
| `+term` | 必須ターム（必ず含む） | `+python` |
| `-term` | 除外ターム（含まない） | `-deprecated` |
| `"phrase"` | クォート付きフレーズ（完全一致） | `"機械学習"` |
| `OR` | 論理 OR | `python OR ruby` |
| `(expr)` | グループ化 | `+(tutorial OR guide)` |

## 使用例

### 基本的な検索

```python
from mygramdb_client import simplify_search_expression

# 単一のターム
expr = simplify_search_expression('python')
# main_term='python', and_terms=[], not_terms=[]

# 複数のターム（暗黙の AND）
expr = simplify_search_expression('python tutorial')
# main_term='python', and_terms=['tutorial'], not_terms=[]
```

### 必須ターム

```python
# + で必須ターム
expr = simplify_search_expression('+python +tutorial')
# main_term='python', and_terms=['tutorial'], not_terms=[]
```

### 除外ターム

```python
# - でターム除外
expr = simplify_search_expression('python -deprecated -old')
# main_term='python', and_terms=[], not_terms=['deprecated', 'old']
```

### 組み合わせ

```python
# 必須、オプション、除外を組み合わせ
expr = simplify_search_expression('+python tutorial -deprecated')
# main_term='python', and_terms=['tutorial'], not_terms=['deprecated']
```

### フレーズ検索

```python
# クォート付きフレーズ
expr = simplify_search_expression('"機械学習" チュートリアル')
# main_term='"機械学習"', and_terms=['チュートリアル'], not_terms=[]

# 必須フレーズ
expr = simplify_search_expression('+"ディープラーニング" -入門')
# main_term='"ディープラーニング"', and_terms=[], not_terms=['入門']
```

### 複雑な式

```python
from mygramdb_client import parse_search_expression, has_complex_expression

# OR 式
expr = parse_search_expression('python OR ruby')
# has_complex_expression(expr) == True

# グループ式
expr = parse_search_expression('+(tutorial OR guide) python')
# has_complex_expression(expr) == True
```

## クライアントでの使用

```python
from mygramdb_client import MygramClient, SearchOptions, simplify_search_expression

async def search_with_expression():
    client = MygramClient()
    await client.connect()

    # ユーザー入力をパース
    user_query = 'golang チュートリアル -非推奨'
    expr = simplify_search_expression(user_query)

    # 検索で使用
    results = await client.search('articles', expr.main_term, SearchOptions(
        and_terms=expr.and_terms,
        not_terms=expr.not_terms,
        limit=100
    ))

    print(f"{results.total_count} 件見つかりました")
    await client.disconnect()
```

## 全角スペースのサポート

パーサーは全角スペース（U+3000）を半角スペースに正規化するため、日本語テキスト入力をサポートしています：

```python
# 全角スペースは半角スペースとして扱われる
expr = simplify_search_expression('日本語　検索')  # U+3000 スペース
# 以下と同じ: simplify_search_expression('日本語 検索')
```

## エラーハンドリング

```python
from mygramdb_client import simplify_search_expression

# 空の式は ValueError を発生
try:
    expr = simplify_search_expression('')
except ValueError as e:
    print(f"エラー: {e}")  # "Search expression cannot be empty"

# 閉じていないクォートは ValueError を発生
try:
    expr = simplify_search_expression('"閉じていない')
except ValueError as e:
    print(f"エラー: {e}")  # "Unterminated quoted string at position 0"

# 除外タームのみは ValueError を発生
try:
    expr = simplify_search_expression('-spam -deprecated')
except ValueError as e:
    print(f"エラー: {e}")  # "Search expression must have at least one positive term"
```

## API リファレンス

### SearchExpression

```python
@dataclass
class SearchExpression:
    required_terms: List[str] = field(default_factory=list)  # + プレフィックス付きターム
    excluded_terms: List[str] = field(default_factory=list)  # - プレフィックス付きターム
    optional_terms: List[str] = field(default_factory=list)  # プレフィックスなしターム
    raw_expression: str = ""                                 # 元の式（複雑な式用）
```

### SimplifiedExpression

```python
@dataclass
class SimplifiedExpression:
    main_term: str                                    # 最初の正のターム
    and_terms: List[str] = field(default_factory=list)  # 追加の AND ターム
    not_terms: List[str] = field(default_factory=list)  # 除外ターム
```

### 関数

| 関数 | 説明 |
|------|------|
| `parse_search_expression(expr)` | SearchExpression にパース |
| `simplify_search_expression(expr)` | SimplifiedExpression にパース |
| `convert_search_expression(expr)` | QueryAST 文字列に変換 |
| `has_complex_expression(expr)` | OR/グループ化をチェック |
| `to_query_string(expr)` | SearchExpression をクエリ文字列に変換 |
