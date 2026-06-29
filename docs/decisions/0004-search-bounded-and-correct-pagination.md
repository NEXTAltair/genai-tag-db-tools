---
type: ADR
title: "ADR 0004: Bounded and Correct Search Pagination"
status: Accepted
timestamp: 2026-06-02
deciders: NEXTAltair
tags: []
---

# ADR 0004: Bounded and Correct Search Pagination

## Context

ADR 0003 で `search` に既定 `--limit 50` を導入した結果、ページングの正確性と検索コストの両立が問題になった。

`core_api.search_tags` の post-filter(`_filter_rows`: alias / deprecated / usage / 複数 format・type)は repository クエリの **後** に Python 側で走る。一方 `TagRepository.search_tags` → `TagSearchQueryBuilder.initial_tag_ids` は LIMIT をキーワード一致段階(format/type/alias フィルタ・translation 重複排除の前)で適用する。このため:

- limit を素朴に pushdown すると、先頭 N 件が alias/deprecated や別 format で埋まると有効な一致を取りこぼし、`total` も raw 件数でキャップされる。
- 一方 LIMIT を完全に外すと、autocomplete(`tag_suggestion_service` が毎キーストロークで `limit≈20` を設定)が全一致を materialize して劣化する(LoRAIro#602)。

重要な事実: `TagSearchResultBuilder._resolve_status_info` は **format 指定時のみ** alias/deprecated/usage/type を解決する。format 無指定の plain keyword 検索では全行が `alias=False, deprecated=False` になり、post-filter は何も落とさない。

## Decision

- **`initial_tag_ids`: dedup してから limit** — tag/translation の id クエリを UNION(DISTINCT)+ `order_by(tag_id)` してから limit/offset を適用する。各クエリを個別に limit して set union する旧実装は、同一タグの多言語 translation 行が窓を食い潰しユニーク tag_id 数が limit 未満になっていた。
- **`core_api.search_tags`: plain keyword(format/type/usage 制約なし)のときだけ limit/offset を repository に pushdown** して bound する(typeahead / autocomplete 経路、preload も page 件数に限定)。制約付き検索は unbounded fetch → `_filter_rows` → Python paging で正確性を優先する。`total` は制約付きで正確、bounded パスで None。
- **offset は `MergedTagReader` に pushdown しない** — `_merge_by_key` は limit/offset を各 backing DB に転送し merge 後に再適用しないため、`limit+offset` 件を取得して merge 後に Python で `[offset:offset+limit]` をスライスする。

## Rationale

over-fetch のようなヒューリスティックは「窓を何件にするか」の閾値問題が残り、format/translation のエッジで取りこぼす。post-filter がドロップするのは制約があるときだけ、という構造を使えば、plain keyword は SQL LIMIT が安全(=bounded)、制約付きは unbounded だが正確、と用途に応じて両立できる。autocomplete は plain keyword なので bounded のまま、CLI の絞り込み検索は per-keystroke ではないので unbounded を許容できる。

## Consequences

単一 DB では correct かつ bounded を達成する。**複数 backing DB を持つ `MergedTagReader` のページングは近似のまま残る**(per-repo limit が cross-repo dedup の前に走るため、DB 間で tag_id が重複すると merged 窓が limit 未満に縮みうる)。これは merge 構造に由来する既存特性で、本決定で悪化はしていない。本質的対応(複数 DB を跨ぐ単一クエリ / merge-aware adaptive fetch)は **#39** に、repository 層への filter pushdown は **#37** に切り出す。
