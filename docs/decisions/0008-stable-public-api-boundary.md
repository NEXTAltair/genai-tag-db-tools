---
type: ADR
title: "ADR 0008: Stable Public API Boundary"
status: Accepted
timestamp: 2026-06-29
deciders: NEXTAltair
tags: [public-api, packaging, service-layer]
depends_on: [pydantic]
---

# ADR 0008: Stable Public API Boundary

## Context

LoRAIro をはじめとする下流プロジェクトは genai-tag-db-tools を **ライブラリ（in-process）**
として取り込み、`genai_tag_db_tools.db.repository.MergedTagReader` や
`genai_tag_db_tools.services.*` などの内部モジュールを直接 import していた。これにより、
内部リファクタ（overlay 再設計 #65、サービス分割など）が下流を容易に壊す状態になっていた。

一方で CLI（ADR 0003/0005）はプロセス境界で安定契約を提供するが、Python 型を直接扱いたい
in-process 消費者には不向きで、CLI だけでは下流の安定性を担保できない。

## Decision

**安定 public API はトップレベル `genai_tag_db_tools` パッケージに集約**し、下流は
そこ（または `genai_tag_db_tools.api` / `genai_tag_db_tools.models`）からのみ import する。
`genai_tag_db_tools.db.*` / `genai_tag_db_tools.services.*` などの内部モジュールへの依存を禁止する。

- リーダ／ライタ／登録サービスは不透明な Protocol ハンドル（`TagReaderProtocol` 等）として公開し、
  実体はファクトリ（`get_tag_reader` / `get_user_tag_reader` / `create_tag_register_service` /
  `get_user_repository`）経由で取得する。
- コア操作はモジュールレベル関数（`search_tags` / `convert_tags` / `register_tag` /
  `recommend_manual_refinement` / `apply_approved_feedback` ...）として公開する。
- 旧来の内部 import から移行しやすいよう、後方互換の別名（`MergedTagReader = TagReaderProtocol`、
  `get_default_reader = get_tag_reader`）を提供する。

## Rationale

- in-process 消費者（GUI、LoRAIro）に対して、内部実装と切り離した安定面を1か所で約束できる。
- Protocol ＋ ファクトリにより、内部クラス構造を変えても公開シグネチャを保てる。
- CLI（プロセス境界）と public API（in-process）は別クラスの消費者に対応する別アダプタであり、
  どちらもコア（`core_api` / `services`）の薄いラッパに留める（ports & adapters）。

## Consequences

- 公開シンボルの増減は破壊的変更として扱い、`__all__` で明示管理する。
- 下流（LoRAIro 等）は内部 import から public API への移行が必要。import 行の差し替えで済むよう
  別名を用意した。
- ドキュメント（README）の例も public API 経由に統一する（内部モジュール直 import を案内しない）。
