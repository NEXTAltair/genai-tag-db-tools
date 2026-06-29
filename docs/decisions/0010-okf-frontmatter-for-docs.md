---
type: ADR
title: "ADR 0010: OKF YAML Frontmatter for Documentation"
status: Accepted
timestamp: 2026-06-29
deciders: NEXTAltair
tags: [docs, frontmatter, metadata]
depends_on: [yaml]
---

# ADR 0010: OKF YAML Frontmatter for Documentation

## Context

ADR 0001–0009 までは ADR 限定で YAML frontmatter（`type` / `title` / `status` /
`timestamp` / `deciders` / `tags`）を導入した（#103, PR #104）。しかし `docs/` 配下の
非 ADR ドキュメント（`README.md` / `docs/cli.md` / `docs/investigations/**` /
`docs/superpowers/**`）には共通の frontmatter 規約が無く、種別もまちまちだった。

下流の LoRAIro は ADR 0069 で OKF（Open Knowledge Foundation 風）YAML frontmatter を
ドキュメントの SSoT として扱う方針を採り、通常ドキュメントへも拡張する方針を
LoRAIro#971 で定義している。本リポジトリは LoRAIro に消費される下流パッケージであり、
横断検索・索引生成・エージェント参照を揃えるため、同じ frontmatter 規約に寄せる。

参考: LoRAIro ADR 0069 / LoRAIro#971（OKF frontmatter policy for documentation）。

## Decision

`docs/` 配下の Markdown ドキュメントは、先頭に **YAML frontmatter（`---` で囲む）** を
持つことを規約とする。LoRAIro#971 の OKF 仕様に準拠する。

### フィールド

| キー | 必須 | 説明 |
|------|------|------|
| `type` | ✅ | 文書種別（下記語彙） |
| `title` | ✅ | 表示タイトル |
| `status` | ✅ | 状態（下記語彙） |
| `timestamp` | ✅ | 作成日・決定日・最終重要更新日。`YYYY-MM-DD` |
| `tags` | 任意 | 機能・責務・動作の抽象分類（技術名は入れない） |
| `depends_on` | 任意 | 強く依存する技術・ライブラリ・外部仕様 |
| `deciders` | ADR のみ | 決定者 |

- `version` は**持たない**。版・鮮度は `timestamp` と Git 履歴で扱う。
- `type` と重複する分類は `tags` に入れない（例: `type: Contract` の文書で `tags: [contract]` としない）。
- 内部 package 名はファイルパスで判別できるため、`packages` のような frontmatter は持たない。

### `type` 語彙

`ADR` / `Guide` / `Reference` / `Contract` / `Plan` / `Investigation` / `Report`

| type | 用途 | 本リポジトリでの例 |
|------|------|--------------------|
| `ADR` | 設計判断記録 | `docs/decisions/0001–0010` |
| `Contract` | 機械可読な入出力契約 | `docs/cli.md` |
| `Reference` | 概要・設計・参照資料 | `README.md`, `docs/decisions/README.md`, 設計 spec |
| `Plan` | 実装計画 | `docs/superpowers/plans/**` |
| `Investigation` | 調査記録 | `docs/investigations/**` |
| `Guide` | 手順・ハウツー | （現状なし） |
| `Report` | 結果報告 | （現状なし） |

### `status` 語彙

`Draft` / `Accepted` / `Implemented` / `Deprecated` / `Superseded`

- ADR は従来どおり `Proposed` / `Accepted` / `Deprecated` / `Superseded by [XXXX]` を使う。
- 計画・設計など「記述対象が実装済み」の文書は `Implemented` を使ってよい。

### `tags` 語彙（抽象的な機能・責務・動作）

技術名ではなく機能分類に寄せる。本リポジトリで使う最小語彙:

`cli` / `gui-view` / `search` / `pagination` / `db-read` / `db-write` /
`db-migration` / `schema` / `overlay` / `tag-normalization` / `tag-conversion` /
`recommendation` / `feedback` / `advisory` / `public-api` / `service-layer` /
`introspection` / `validation` / `error-handling` / `config` / `packaging` /
`overview` / `adr` / `index` / `docs` / `frontmatter` / `metadata`

新しい分類が必要になったら、まず既存語彙で表せないか確認し、足りなければ本 ADR の
語彙表に追記する。

### `depends_on` 語彙（技術・ライブラリ・外部仕様）

`pyside6` / `sqlalchemy` / `sqlite` / `alembic` / `pydantic` / `polars` / `numpy` /
`huggingface-hub` / `argparse` / `yaml`

### 適用範囲

必須対象:

- `docs/**/*.md`
- `README.md`（プロジェクト概要として `type: Reference` を付与する）

対象外（frontmatter を付けない）:

- `CHANGELOG.md` / `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`
- 外部ツールが固定フォーマットを要求するファイル
- 生成物（generated docs）、`.pytest_cache/**` などのキャッシュ

### 移行方針

- 既存 ADR 0001–0009 は PR #104 で frontmatter 化済み。本 ADR で `tags` を抽象語彙へ
  見直し、必要に応じ `depends_on` を補う。
- 非 ADR の既存ドキュメントは本 ADR と同じ変更で frontmatter を付与・整合する。
- 以後の新規ドキュメントは本規約に従って作成する。

## Rationale

- `type` を必須・語彙固定にすることで、種別ごとの索引・フィルタが安定する。
- 技術依存を `tags` から `depends_on` に分離することで、`tags` を「何をするか」、
  `depends_on` を「何の上で動くか」に役割分担でき、検索ノイズが減る。
- LoRAIro と同一規約にすることで、モノレポ横断のドキュメントツール（okf-bundle 等）を
  そのまま下流パッケージへ適用できる。

## Consequences

- 全 `docs/**` と `README.md` が機械可読な frontmatter を持つ。
- `docs/decisions/README.md` の ADR テンプレートは frontmatter 付きを継続する。
- validation（CI / Make target / okf-bundle の validate）を将来導入する場合、対象は
  「適用範囲」節のディレクトリ、除外は「対象外」節のファイルとする（本 ADR では
  validation 自動化までは行わない。語彙・対象の定義のみ）。

## Alternatives Considered

- **ADR のみ frontmatter を維持**: 非 ADR ドキュメントの横断索引ができず、LoRAIro 規約と
  乖離するため不採用。
- **`tags` に技術名も混在**: `tags: [cli, sqlalchemy]` のように混ぜる案。機能分類と技術
  依存が混ざり検索性が落ちるため、`depends_on` への分離を採用。

## References

- #103（docs 整合 issue）/ PR #104（ADR frontmatter 導入）
- LoRAIro ADR 0069 / LoRAIro#971
