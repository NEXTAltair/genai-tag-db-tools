---
type: ADR
title: "ADR 0006: Search Filter Pushdown and Merged Pagination"
status: Accepted
timestamp: 2026-06-03
deciders: NEXTAltair
tags: [search, pagination, db-read, overlay]
depends_on: [sqlalchemy, sqlite]
---

# ADR 0006: Search Filter Pushdown and Merged Pagination

## Context

ADR 0004 では plain keyword 検索だけを bounded にし、format/type/usage などの制約付き検索は
正確性のため unbounded fetch 後に Python 側で絞り込んでいた。また、複数 backing DB を持つ
`MergedTagReader` は各 repo の `limit` 適用後に merge するため、merge 後ページングが近似だった。

## Decision

- `TagSearchQueryBuilder` は keyword 一致の `UNION DISTINCT` を候補集合にし、format/type/usage/
  alias/deprecated/language を SQL の `EXISTS` 条件で適用してから `ORDER BY tag_id` と
  `LIMIT/OFFSET` を適用する。
- `TagReader.search_tags` は既存の単数 `format_name` / `type_name` APIを維持しつつ、core API 用に
  複数 `format_names` / `type_names` と `deprecated` 条件を受け取る。
- `MergedTagReader.search_tags` は `limit/offset` を repo 別ページングとして扱わず、各 repo から
  chunk を取得し、`tag_id` で dedup した後に merged result へ `offset/limit` を適用する。
- `core_api.search_tags` の bounded path では `total=None` を返す。正確な total が必要な
  unbounded path では全件取得後の件数を返す。

## Consequences

autocomplete/typeahead は bounded のまま、制約付き検索も full candidate materialize を避けられる。
複数DB検索では既存の `TagReader(session_factory)` 構成を維持するため、SQLite `ATTACH DATABASE`
ではなく adaptive fetch を採用する。

## Amendment (2026-06-03, #45)

フィルタの正本を repository 層 (`filtered_tag_ids`) に一元化し、`core_api.search_tags` の
Python 側再フィルタ (`_filter_rows`) を撤去した。

`_filter_rows` は `row["usage_count"]` / `row["deprecated"]` 等で再判定していたが、
`TagSearchResultBuilder.build_row` はこれらを**単一 concrete format のときだけ**埋める
(無/複数 format = `format_id=0` では `usage_count=0` / `deprecated=False` / `type_name=""`)。
そのため `tag-db search --query x --min-usage N`(format 無し)で、repository が `EXISTS` で
正しく拾った行を `_filter_rows` が `usage_count(0) < N` で全 drop し、空を返していた (#45)。

repository は本 ADR の `EXISTS` push-down で format/type/usage/alias/deprecated を既に適用済みの
ため、`_filter_rows` は冗長かつ format 依存値で誤判定する。撤去により正本は repository 単一に
なる。回帰テストでは `DummyRepo` を `build_row` 同様にゼロ詰め(無/複数 format で format 依存
フィールドを 0/False/"")して、二重フィルタが再導入されたら落ちるようにした。
