---
type: Reference
title: Architecture Decision Records
status: Accepted
timestamp: 2026-06-29
tags: [adr, index]
---

# Architecture Decision Records

genai-tag-db-tools の重要な設計判断を記録するドキュメント群。各 ADR は先頭に YAML
frontmatter（`type` / `title` / `status` / `timestamp` / `deciders` / `tags`、必要に応じ
`depends_on`）を持つ。docs 全体の frontmatter 規約は [ADR 0010](0010-okf-frontmatter-for-docs.md) を参照。

<!-- OKF-TABLE:START -->
| ADR | タイトル | 日付 | ステータス |
|---|---|---|---|
| [0001](0001-cli-default-database-source-policy.md) | ADR 0001: CLI Default Database Source Policy | 2026-06-02 | Accepted |
| [0002](0002-cli-gui-entrypoint-policy.md) | ADR 0002: CLI and GUI Entrypoint Policy | 2026-06-02 | Accepted |
| [0003](0003-cli-jsonl-output-and-error-contract.md) | ADR 0003: CLI JSONL Output and Structured Error Contract | 2026-06-02 | Accepted |
| [0004](0004-search-bounded-and-correct-pagination.md) | ADR 0004: Bounded and Correct Search Pagination | 2026-06-02 | Accepted |
| [0005](0005-cli-command-introspection.md) | ADR 0005: CLI Command Introspection Contract | 2026-06-02 | Accepted |
| [0006](0006-search-filter-pushdown-and-merged-pagination.md) | ADR 0006: Search Filter Pushdown and Merged Pagination | 2026-06-03 | Accepted |
| [0007](0007-user-overlay-patch-db.md) | ADR 0007: User Overlay Patch DB | 2026-06-29 | Accepted |
| [0008](0008-stable-public-api-boundary.md) | ADR 0008: Stable Public API Boundary | 2026-06-29 | Accepted |
| [0009](0009-recommendation-advisory-and-feedback-routing.md) | ADR 0009: Recommendation Advisory and Feedback Routing | 2026-06-29 | Accepted |
| [0010](0010-okf-frontmatter-for-docs.md) | ADR 0010: OKF YAML Frontmatter for Documentation | 2026-06-29 | Accepted |
| [0011](0011-recommend-cli-followups.md) | ADR 0011: Recommendation CLI Follow-up Adapters | 2026-06-29 | Accepted |
<!-- OKF-TABLE:END -->

> このテーブルは `make adr-index` が frontmatter から生成する。手編集しない。

## ADR テンプレート

```markdown
---
type: ADR
title: "ADR XXXX: タイトル"
status: Proposed | Accepted | Deprecated | Superseded by [XXXX]
timestamp: YYYY-MM-DD
deciders: NEXTAltair
tags: []
depends_on: []
---

# ADR XXXX: タイトル

## Context

なぜこの決定が必要だったか。問題の背景と制約。

## Decision

何を決定したか。

## Rationale

なぜこの選択をしたか。他の選択肢との比較。

## Consequences

この決定による影響。良い点・悪い点・トレードオフ。
```
