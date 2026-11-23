---
type: Reference
title: Search categories (TAG_CATEGORIES)
description: 公開 base DB の検索分類を読む API・検索条件・CLI の契約 (Issue #153)
status: Accepted
timestamp: 2026-11-23
tags: [public-api, search, categories, db-read, cli]
depends_on: [sqlalchemy, sqlite]
---

# Search categories

公開 base DB (CC0 版 `v2026.10.13.01` 以降) は、旧タグ表から取り込んだ階層的な検索分類を
`TAG_CATEGORIES` / `TAG_CATEGORY_MEMBERSHIPS` に持つ。テーブル定義と取り込みの正本は
dataset builder の `core/enrichment.py`。検索分類は booru のタグ type
(`general` / `artist` / `character` ...) とは別の情報で、`type_names` 条件とは独立に扱う。

- `category_id` は namespace と path から作られた安定 ID。DB を跨いで同じ分類を指すので、
  利用側で作り直さない。
- namespace (`prompt-generator` / `prompt-manager-203` 等) は元表の分類体系で、namespace を
  跨いだ意味の統合はしていない。
- 階層は `parent_id` (ルートは `None`)・`depth` (ルートが 1)・`path` (ルートからのラベル列) で表す。

## 読み取り API

すべてトップレベル `genai_tag_db_tools` から import する (ADR 0008)。リーダは
`get_tag_reader()` / `get_user_tag_reader()` で取得し、`TagCategoryReaderProtocol` として扱う。

| 関数 | 戻り値 | 分類が未収録のとき |
|---|---|---|
| `get_tag_category_database_info(reader)` | base DB ごとの `TagCategoryDatabaseInfo` (優先順): `version` (DATABASE_METADATA) / `has_categories` / `category_count` / `membership_count` | `has_categories=False`、件数 0 |
| `list_tag_categories(reader, namespace=None)` | `list[TagCategory]` (namespace → path 順)。複数 DB の同じ `category_id` は 1 つにまとめる | 空リスト |
| `list_tag_category_namespaces(reader)` | namespace 名の昇順リスト | 空リスト |
| `get_tag_categories_batch(reader, tag_ids)` | 分類を持つ tag_id → `list[TagCategory]` | 空 dict (分類の無い tag_id はキーを持たない) |

`get_tag_categories_batch` は検索結果 1 ページ分の tag_id をまとめて渡す。base DB ごとに
1 回の SQL で所属を取得し、分類を持つ tag_id だけ所有タグを解決するので、SQL の数は件数に比例しない。

user DB (overlay) は分類を持たず、作成もしない。user 独自タグは分類に所属しない。

### 型注釈 (mypy strict の利用側)

`get_tag_reader()` / `get_user_tag_reader()` の戻り値型は既存互換のため `TagReaderProtocol` のままで、
分類メソッドを含まない。型チェックを有効にした利用側では `TagCategoryReaderProtocol` へ `cast` してから渡す
(実体のリーダはこの Protocol を満たす)。

```python
from typing import cast

from genai_tag_db_tools import TagCategoryReaderProtocol, get_tag_reader, list_tag_categories

reader = cast(TagCategoryReaderProtocol, get_tag_reader())
categories = list_tag_categories(reader)
```

### version / revision の確認

`version` は DB ファイル内の `DATABASE_METADATA` の値で、いま読み込んでいるファイルの版を表す。
Hugging Face 上の公開更新は既存のローカルキャッシュを書き換えない。どの revision のファイルを
読んでいるかは `initialize_databases()` / `ensure_databases()` の結果 (`db_path` / `revision`) で確認する。

## 分類条件付き検索

`TagSearchRequest` に次の 2 項目を追加した。

| 項目 | 既定 | 意味 |
|---|---|---|
| `category_ids` | `None` | 分類 ID の絞り込み。複数指定は **OR** (`format_names` / `type_names` と同じ)。`None` と空リストは条件なし |
| `include_descendant_categories` | `True` | 指定分類の子孫分類に所属するタグも含める |

- 分類だけで探すときは `query=""` (既定の `partial=True`) を使う。部分一致の空 query は既存どおり
  全タグに一致し、分類条件で絞られる。
- 存在しない `category_id` は何にも一致しない (存在しない format 名と同じ)。
- 条件は format / type / usage / alias / deprecated / language と併用でき、すべて **repository 側で
  適用してから重複排除し、その後に `offset` / `limit`** を適用する (ADR 0006)。タグが複数の分類に
  所属していても結果の行は重複しない。bounded 検索 (`limit` 指定) の `total=None` は変わらない。
- 条件は一致したタグ (alias 解決前) に適用する。format / type 等の既存条件と同じ。
- 分類条件の無い検索は、分類テーブルの確認を含め追加の SQL を発行しない。

### 複数 DB と user overlay

- 各 base DB で、その DB の分類テーブルを使って所属を解決してから既存の merge 規則に従う。
- 別 DB に同じ数値 `tag_id` の別タグがあっても、その DB の `TAGS.tag` が一致しない所属は使わない
  (無関係なタグへ分類を付けない)。
- user 翻訳パッチ経由で一致した base タグも、所属を確かめてから残す。

#### 制約: 衝突した tag_id の行に `get_tag_categories_batch` を使う場合

`get_tag_categories_batch` は tag_id だけを受け取り、その tag_id が指すタグを既存の解決規則
(user → 優先度の高い base DB) で決める。複数 base DB で同じ数値 tag_id が別のタグを指すとき、
分類条件付き検索は分類を持つ DB の行 (例: 低優先 DB の `(4, "smile")`) を返すが、その tag_id を
`get_tag_categories_batch` に渡すと最優先 DB の同じ ID の別タグ (例: `(4, "cat")`) として解決され、
分類は空 (キーなし) になる。無関係なタグに分類を付けないための挙動で、結果の行と batch の解決先が
食い違うのはこの衝突のときだけである。

回避方法:

- 分類条件付き検索の結果は、条件に指定した分類 (`include_descendant_categories=True` なら子孫を含む)
  のいずれかに所属することが保証される。行の分類が条件の分類で足りる場合は、それを使う。
- 行の全分類が必要なら、その行を返した base DB だけを読み込んだリーダ (`database_runtime_scope()` 内で
  対象 DB だけを初期化する、CLI なら `--base-db` を 1 つだけ指定する) で `get_tag_categories_batch` を呼ぶ。

### 旧 DB との互換

分類テーブルの無い旧 CC0 / MIT / CC BY DB でも、通常の検索と翻訳取得はそのまま動く。分類 API は上表の
「未収録」の値を返し、分類条件付き検索はその DB から何も返さない。テーブル不存在の SQL 例外は出さない。

### read-only と runtime scope

分類の読み取りは既存 DB を読むだけで、base DB へのテーブル作成・migration・書き込みはしない。
分類テーブルは read-only 初期化の必須テーブルに含めないため、旧 DB も `read_only=True` で開ける。
分類の有無はリーダが接続している DB をその都度確認し、プロセス全体のキャッシュを持たないので、
`database_runtime_scope()` の切り替え・入れ子で別 DB に漏れない
([Database runtime scope](database-runtime-scope.md))。

## CLI

```bash
tag-db categories [--namespace NAME]          # 分類ノード一覧 + base DB ごとの収録状況
tag-db search --query "" --category-id ID [--category-id ID2] [--no-category-descendants]
```

詳細は [CLI contract](cli.md) の `categories` / `search` を参照。
