# python-mygramdb-client

[![CI](https://img.shields.io/github/actions/workflow/status/libraz/python-mygramdb-client/ci.yml?branch=main&label=CI)](https://github.com/libraz/python-mygramdb-client/actions)
[![PyPI](https://img.shields.io/pypi/v/mygramdb-client)](https://pypi.org/project/mygramdb-client/)
[![codecov](https://codecov.io/gh/libraz/python-mygramdb-client/branch/main/graph/badge.svg)](https://codecov.io/gh/libraz/python-mygramdb-client)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.9-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](https://github.com/libraz/python-mygramdb-client)

[MygramDB](https://github.com/libraz/mygram-db/) 用の Python クライアントライブラリ — MySQL レプリケーションをサポートする高性能インメモリ全文検索エンジン。

> **MygramDB v1.8** 対応（引用符なしのブール式送信、FACET の `#` 値の保持）。v1.7 機能（マルチデータベース、ブール検索 `search_raw`、ランタイム変数、オンデマンド同期）および v1.6 機能（ファジー検索、ハイライト、ファセット、BM25）も継続サポート。

## 概要

MygramDB は MySQL FULLTEXT の **25〜200倍高速** な全文検索を提供します。このクライアントは MygramDB の TCP テキストプロトコル（memcached スタイル）で通信し、外部依存はゼロです。

| | MySQL FULLTEXT | MygramDB |
|---|---|---|
| **検索速度** | ベースライン | 25〜200倍高速 |
| **ストレージ** | ディスク | インメモリ |
| **レプリケーション** | — | MySQL binlog |
| **プロトコル** | MySQL | TCP（memcached スタイル） |

### 特徴

- **外部依存ゼロ** — 標準ライブラリのみ
- **Async/Await API** — コンテキストマネージャ対応のモダンな asyncio ベースインターフェース
- **コネクションプール** — 高スループット用途向けの組み込み `MygramPool`（コマンド単位のリトライ、サーキットブレーカー、観測フック付き）
- **堅牢なトランスポート** — 自動再接続、connect/command 別々のタイムアウト、TCP キープアライブ
- **検索式パーサー** — Web スタイルの検索構文（+必須、-除外、"フレーズ"、OR、グループ化）
- **完全なプロトコルサポート** — すべての MygramDB コマンド（SEARCH、COUNT、GET、INFO、CACHE、DUMP、OPTIMIZE など）
- **型安全性** — dataclass による完全な型ヒント。PEP 561 の `py.typed` マーカーを同梱
- **入力バリデーション** — 制御文字インジェクションに対する組み込み保護

## インストール

```bash
pip install mygramdb-client
```

### ソースからインストール

```bash
git clone https://github.com/libraz/python-mygramdb-client.git
cd python-mygramdb-client
rye sync
```

## クイックスタート

```python
import asyncio
from mygramdb_client import MygramClient, ClientConfig, SearchOptions

async def main():
    async with MygramClient(ClientConfig(host='localhost', port=11016)) as client:
        # 検索
        results = await client.search('articles', 'hello', SearchOptions(limit=100))
        print(f"{results.total_count} 件の結果が見つかりました")

        # カウント
        count = await client.count('articles', 'technology')
        print(f"カウント: {count.count}")

        # ID でドキュメントを取得
        doc = await client.get('articles', '12345')
        print(f"Doc: {doc.primary_key} {doc.fields}")

asyncio.run(main())
```

## 検索式

Web スタイルの検索クエリを構造化された検索パラメータにパースします：

```python
from mygramdb_client import simplify_search_expression

# スペース = AND、- = NOT、"" = フレーズ、OR = OR、() = グループ化
expr = simplify_search_expression('hello world -spam')
# expr = SimplifiedExpression(main_term='hello', and_terms=['world'], not_terms=['spam'])

results = await client.search('articles', expr.main_term, SearchOptions(
    and_terms=expr.and_terms,
    not_terms=expr.not_terms,
    limit=100,
    offset=50,
    filters={'status': 'published', 'lang': 'ja'},
    sort_column='created_at',
    sort_desc=True,
))
```

## MygramDB v1.6 機能

```python
from mygramdb_client import HighlightOptions, FacetOptions, SearchOptions

# BM25 相関スコアリング
result = await client.search('articles', 'python',
    SearchOptions(sort_column='_score', sort_desc=True))

# ファジー検索（レーベンシュタイン距離 1 または 2）
result = await client.search('articles', 'helo',
    SearchOptions(fuzzy=1))

# ハイライト付きスニペット
result = await client.search('articles', 'python',
    SearchOptions(highlight=HighlightOptions(
        open_tag='<mark>', close_tag='</mark>',
        snippet_len=150, max_fragments=3,
    )))
for r in result.results:
    print(r.primary_key, r.snippet)

# ファセット集計
facets = await client.facet('articles', 'category',
    FacetOptions(query='python', limit=10))
for v in facets.results:
    print(f'{v.value}: {v.count}')
```

## MygramDB v1.7 機能

### マルチデータベース（修飾テーブル識別子）

v1.7+ のインスタンスは複数のデータベースのテーブルをインデックス化できます。
テーブルは `database.table` の形式で参照します。単一データベースのサーバーでは
従来どおりテーブル名のみでも動作します。

```python
from mygramdb_client import qualify_table_identity, parse_table_identity

await client.search('app_db.articles', 'hello')

qualify_table_identity('articles', 'app_db')  # 'app_db.articles'
parse_table_identity('app_db.articles')       # ('app_db', 'articles')
```

### ブール検索

`search()` はクエリを単一の（自動的に引用符で囲まれた）トークンとして送信します。
`AND`/`OR`/`NOT`/グループ化を含むブール式は、式を組み立てて `search_raw()` に
渡します。`search_raw()` は式をそのまま（引用符なし、MygramDB v1.8+）送信するため、
サーバーの AST パーサがネストした構造を解釈できます：

```python
from mygramdb_client import convert_search_expression, SearchRawOptions

raw = convert_search_expression('python OR (ruby AND rails)')
res = await client.search_raw('articles', raw, SearchRawOptions(limit=50))

# search_with_highlights / search_raw_with_highlights は HIGHLIGHT 句を有効化します
res = await client.search_with_highlights('articles', 'python')
```

### ランタイム変数とオンデマンド同期

```python
await client.set_variable('logging.level', 'info')
print(await client.show_variables('logging%'))

await client.sync('app_db.articles')
print(await client.sync_status())
await client.sync_stop('app_db.articles')
```

## MygramDB v1.8 機能

v1.8 はクライアントが利用する 2 つのワイヤープロトコルの挙動を改善します。

- **引用符なしのブール式送信** — `search_raw()` は式を引用符なしで送信するため、
  サーバーが `AND`/`OR`/`NOT` とグループ化（AND の下にネストした OR グループを
  含む）を解釈できます。制御文字は送信前に拒否されます。
- **FACET の `#` 値の保持** — `#` で始まる `facet()` の値は保持されます。FACET
  レスポンスの中でタブを含まない `#` 行のみがコメントとして扱われます。

```python
# サーバー側でパースされるブール式（引用符なしで送信）
raw = convert_search_expression('python OR (ruby AND rails)')
res = await client.search_raw('articles', raw, SearchRawOptions(limit=50))

# '#hashtag' 形式のファセット値は保持されます
facets = await client.facet('articles', 'tags')
```

## 高スループット: コネクションプール

秒間数百リクエスト規模では、単一接続ではなく `MygramPool` を使用します。
複数の接続に同時リクエストを多重化し、リトライ・サーキットブレーカー・
イベントフックを重ねます。

```python
from mygramdb_client import (
    MygramPool, PoolConfig, ClientConfig,
    RetryPolicy, CircuitBreakerConfig,
)

pool_config = PoolConfig(
    min_connections=4,
    max_connections=32,
    acquire_timeout=2.0,
    retry_policy=RetryPolicy(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, reset_timeout=10.0),
)

async with MygramPool(ClientConfig(host='localhost'), pool_config) as pool:
    # 委譲 API: 取得・実行・返却をまとめて行い、リトライとブレーカーを適用
    result = await pool.search('articles', 'hello')

    # 明示的に接続をチェックアウトすることも可能
    async with pool.acquire() as client:
        await client.count('articles', 'python')

    print(pool.stats())  # PoolStats のスナップショット
```

タイムアウト・自動再接続・観測性の詳細は
[docs/ja/advanced-usage.md](docs/ja/advanced-usage.md) を参照してください。

## 型ヒント

このパッケージは PEP 561 の `py.typed` マーカーを同梱しているため、型チェッカー
（mypy、pyright）はインラインの型注釈を直接利用できます（スタブパッケージ不要）。
完全な型定義が含まれています：

```python
from mygramdb_client import (
    ClientConfig,
    SearchResponse,
    CountResponse,
    Document,
    ServerInfo,
    SearchOptions,
    DumpStatus,
    CacheStats,
)
```

## 開発

```bash
rye sync              # 依存関係をインストール
rye run pytest        # テストを実行
rye run pytest -v     # テストを実行（詳細）
rye run flake8 src tests  # リント
```

## ライセンス

[MIT](LICENSE)
