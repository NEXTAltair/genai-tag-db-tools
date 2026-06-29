---
type: ADR
title: "ADR 0007: User Overlay Patch DB"
status: Accepted
timestamp: 2026-06-29
deciders: NEXTAltair
tags: [database, overlay, schema]
---

# ADR 0007: User Overlay Patch DB

## Context

base DB（Hugging Face から配布される読み取り専用 DB）に対し、ユーザー固有の修正・追加を
保存したい。当初は user DB を base DB と同じスキーマ（`TAGS` / `TAG_STATUS` / ...）の
「もう一つの tag DB」として持たせる案だったが、以下の問題があった。

- base 由来タグへの差分（alias 化、deprecated 化、type 修正、翻訳・使用回数追加）を表現するには、
  base の行をコピーして書き換える必要があり、base 更新との突き合わせ・二重管理が破綻する。
- alias の preferred 先が base タグである場合、user DB 単独では cross-DB 参照を表現できない。
- 「user が触ったのはどの差分か」を base 全体から区別できない。

この検討は epic #2 の派生で、親 issue #65（D+E 方針）と子 #66–#72 として実装した。

## Decision

user DB を base と同列の tag DB ではなく、**`TagRef(scope, tag_id)` を持つ overlay patch DB**
として再設計する。

- `USER_TAGS`: base に存在しないユーザー定義タグ。`tag_id` は `USER_TAG_ID_OFFSET`
  (1,000,000,000) 以上で採番し、base の `tag_id` と衝突させない。
- `USER_TAG_STATUS_PATCH` / `USER_TAG_TRANSLATION_PATCH` / `USER_TAG_USAGE_PATCH`:
  base / user いずれのタグに対しても差分を表す。`target_scope`(`base`|`user`) + `target_tag_id`
  で対象を指す（base への hard FK は持たない）。status patch は `preferred_scope` +
  `preferred_tag_id` で alias 先を cross-DB 指定する。
- status patch の複合 PK は `(target_scope, target_tag_id, format_id)`。同一タグ × format への
  パッチは1行のみ。CHECK 制約で `alias` と preferred の整合（非 alias は自己参照、alias は別参照）を保証する。
- 読み取りは `MergedTagReader` が base reader と `OverlayTagReader` を合成して返す。

## Rationale

- 差分だけを user 側に持つので base 更新と独立し、二重管理が消える。
- `scope` により「base タグへの修正」と「user 新規タグ」を同じ仕組みで扱え、alias の cross-DB
  参照も自然に表現できる。
- base を一切書き換えないため、配布 DB の再ダウンロードや検証が安全。

## Consequences

- 読み取り経路に合成コストが乗る（`OverlayTagReader` ＋ patch のマージ）。
- 旧スキーマの user DB は overlay スキーマへ移行が必要 → user DB 初期化時の自動マイグレーション
  （`detect_legacy_schema` → `migrate_legacy_to_overlay`、user DB 限定・冪等・backup 付き、#72）で対応。
  base はビルド配布のためマイグレーション対象外。
- `Base.metadata`（旧空テーブル）は後方互換のため当面残し、将来削除する。
