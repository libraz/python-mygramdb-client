# python-mygramdb-client

[![CI](https://img.shields.io/github/actions/workflow/status/libraz/python-mygramdb-client/ci.yml?branch=main&label=CI)](https://github.com/libraz/python-mygramdb-client/actions)
[![codecov](https://codecov.io/gh/libraz/python-mygramdb-client/branch/main/graph/badge.svg)](https://codecov.io/gh/libraz/python-mygramdb-client)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.9-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](https://github.com/libraz/python-mygramdb-client)

[MygramDB](https://github.com/libraz/mygram-db/) 用の Python クライアントライブラリ — MySQL レプリケーションをサポートする高性能インメモリ全文検索エンジン。

> **MygramDB v1.7** 対応（マルチデータベース、ブール検索 `search_raw`、ランタイム変数、オンデマンド同期）。v1.6 機能（ファジー検索、ハイライト、ファセット、BM25）も継続サポート。

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
- **検索式パーサー** — Web スタイルの検索構文（+必須、-除外、"フレーズ"、OR、グループ化）
- **完全なプロトコルサポート** — すべての MygramDB コマンド（SEARCH、COUNT、GET、INFO、CACHE、DUMP、OPTIMIZE など）
- **型安全性** — dataclass による完全な型ヒント
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
渡します：

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

## 型ヒント

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
