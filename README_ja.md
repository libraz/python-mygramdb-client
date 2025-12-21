# mygramdb-client

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[MygramDB](https://github.com/libraz/mygram-db/) 用の Python クライアントライブラリ - MySQL FULLTEXT の **25〜200倍高速** な高性能インメモリ全文検索エンジンで、MySQL レプリケーションをサポートしています。

## 特徴

- **Async/Await API** - モダンな asyncio ベースのインターフェース
- **完全なプロトコルサポート** - すべての MygramDB コマンド（SEARCH、COUNT、GET、INFO など）
- **検索式パーサー** - Web スタイルの検索構文（+必須、-除外、"フレーズ"、OR、グループ化）
- **型安全性** - dataclass による完全な型ヒント
- **入力バリデーション** - 制御文字インジェクションに対する組み込み保護
- **デバッグモード** - クエリパフォーマンスメトリクスの組み込みサポート

## インストール

### GitHub からインストール

```bash
pip install git+https://github.com/libraz/python-mygramdb-client.git
```

### rye を使用する場合

```bash
rye add mygramdb-client --git https://github.com/libraz/python-mygramdb-client.git
```

### ソースからインストール

```bash
git clone https://github.com/libraz/python-mygramdb-client.git
cd python-mygramdb-client
rye sync
```

> **Note:** PyPI への登録は将来的に予定しています。

## クイックスタート

```python
import asyncio
from mygramdb_client import MygramClient, ClientConfig, SearchOptions, simplify_search_expression

async def main():
    # 設定を指定してクライアントを作成
    client = MygramClient(ClientConfig(
        host='localhost',
        port=11016
    ))

    await client.connect()

    # Web スタイルの検索式をパース（スペース = AND、- = NOT）
    expr = simplify_search_expression('hello world -spam')
    # expr = SimplifiedExpression(main_term='hello', and_terms=['world'], not_terms=['spam'])

    # AND/NOT 条件で検索
    results = await client.search('articles', expr.main_term, SearchOptions(
        and_terms=expr.and_terms,
        not_terms=expr.not_terms,
        limit=100,
        offset=50,  # MySQL互換: LIMIT 50,100
        filters={'status': 'published', 'lang': 'ja'},
        sort_column='created_at',
        sort_desc=True
    ))

    print(f"{results.total_count} 件の結果が見つかりました")

    # マッチするドキュメントをカウント
    count = await client.count('articles', 'technology')

    # ID でドキュメントを取得
    doc = await client.get('articles', '12345')

    await client.disconnect()

asyncio.run(main())
```

## ドキュメント

- **[はじめに](docs/ja/getting-started.md)** - インストール、設定、基本的な使い方
- **[API リファレンス](docs/ja/api-reference.md)** - 完全な API ドキュメント
- **[検索式](docs/ja/search-expression.md)** - 高度な検索構文ガイド
- **[高度な使い方](docs/ja/advanced-usage.md)** - コネクションプーリング、エラーハンドリング、ベストプラクティス

## 型ヒント

このライブラリは dataclass による完全な型ヒントを提供します：

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

## 開発

```bash
# 依存関係をインストール
rye sync

# テストを実行
rye run pytest

# リント
rye run flake8 src tests
```

## ライセンス

MIT

## 作者

libraz <libraz@libraz.net>

## リンク

- [MygramDB](https://github.com/libraz/mygram-db/) - MygramDB サーバー
- [GitHub](https://github.com/libraz/python-mygramdb-client) - このリポジトリ

## コントリビューション

コントリビューションを歓迎します！お気軽に Pull Request を送信してください。
