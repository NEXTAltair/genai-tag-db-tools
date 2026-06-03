# ADR 0006: Search Filter Pushdown and Merged Pagination

- **日付**: 2026-06-03
- **ステータス**: Accepted

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
