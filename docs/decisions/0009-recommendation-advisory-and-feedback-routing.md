---
type: ADR
title: "ADR 0009: Recommendation Advisory and Feedback Routing"
status: Accepted
timestamp: 2026-06-29
deciders: NEXTAltair
tags: [recommendation, feedback, advisory]
depends_on: [pydantic]
---

# ADR 0009: Recommendation Advisory and Feedback Routing

## Context

epic #2「タグ手動変更リコメンド」は、`needs_manual_refinement(tag: str) -> bool` から始まり、
意味解析・統計・ML・ドメイン知識まで広く検討された。だが `tag` 単体では判定根拠が乏しく、
「保存をブロックする gatekeeper」として使うと大量画像のアノテーション運用のテンポを壊す。
また、明らかな誤タグは user-local の修正に留めず base DB ビルドへ還元したいという要件もあった。

サブ issue #53–#61 として実装した。

## Decision

リコメンドを **advisory（review-assistant）** と位置づけ、反映経路を user-local と base DB で分離する。

- API は `recommend_manual_refinement(tag, repo=None, *, format_name)` を中心に、説明可能な
  `RefinementRecommendation`（`needs_refinement` / `score` / `reasons` / `suggestions` /
  `proposals`）を返す。`needs_manual_refinement(tag) -> bool` は薄い互換ヘルパ。関連 API として
  `recommend_translation_quality` / `recommend_tag_record_refinement`。
- **保存をブロックしない・自動置換しない・read-only**。結果は警告／レビュー優先度／候補提示として使う。
- 反映は2層に分ける:
  - **user-local**: `apply_approved_feedback(...)` が承認済み `ApprovedDbFeedback` を user overlay
    DB にのみ適用し、`LOCAL_FEEDBACK_APPLICATION` に監査記録を残す（base は書き換えない）。
  - **base DB**: 承認済み feedback を correction patch（JSONL）として export → validate → builder
    で apply（CLI `feedback` 群、#58/#60/#61）。builder は validated patch のみを入力にする。

## Rationale

- `bool` だけでは理由・候補・反映可否を返せないため、説明可能な結果型に寄せた。
- gatekeeper を避けることで、保存後レビューやレビューキュー（下流 LoRAIro #931）と整合する。
- user-local と base DB の経路分離により、共有 DB への反映は人間承認＋検証を必須にでき、安全。

## Consequences

- リコメンド自体は DB を書き換えない。書き込みは feedback apply（user-local）／builder apply（base）に限定。
- 下流（LoRAIro）はレビュー UI で本 API を public API 経由で消費する（ADR 0008）。
- CLI からの recommend 露出は別途 issue #102 で対応（public API との parity）。
- **introspection registry（`TOOL_SPECS`, ADR 0005）への登録は runtime のエージェント呼び出し
  対象に限る。** `recommend/*` と `aliases/register`（runtime・user DB 操作）は登録して
  `list-commands` / `describe` に露出するが、**CLI `feedback` 群（base DB ビルド時の保守者/builder
  パイプライン）は意図的に未登録**とする。base patch の validate/export/apply は人間承認＋検証を
  前提とするビルド工程であり、エージェントが実行時に発見・自動実行する runtime コマンド面では
  ないため。この非対称は `tests/unit/test_cli_feedback.py::test_list_commands_unchanged_by_feedback_group`
  で固定する（issue #103）。
