# Architecture Decision Records

genai-tag-db-tools の重要な設計判断を記録するドキュメント群。

| ADR | タイトル | 日付 | ステータス |
|-----|---------|------|-----------|
| [0006](0006-search-filter-pushdown-and-merged-pagination.md) | Search Filter Pushdown and Merged Pagination | 2026-06-03 | Accepted |
| [0005](0005-cli-command-introspection.md) | CLI Command Introspection Contract | 2026-06-02 | Accepted |
| [0004](0004-search-bounded-and-correct-pagination.md) | Bounded and Correct Search Pagination | 2026-06-02 | Accepted |
| [0003](0003-cli-jsonl-output-and-error-contract.md) | CLI JSONL Output and Structured Error Contract | 2026-06-02 | Accepted |
| [0002](0002-cli-gui-entrypoint-policy.md) | CLI and GUI Entrypoint Policy | 2026-06-02 | Accepted |
| [0001](0001-cli-default-database-source-policy.md) | CLI Default Database Source Policy | 2026-06-02 | Accepted |

## ADR テンプレート

```markdown
# ADR XXXX: タイトル

- **日付**: YYYY-MM-DD
- **ステータス**: Proposed | Accepted | Deprecated | Superseded by [XXXX]

## Context

なぜこの決定が必要だったか。問題の背景と制約。

## Decision

何を決定したか。

## Rationale

なぜこの選択をしたか。他の選択肢との比較。

## Consequences

この決定による影響。良い点・悪い点・トレードオフ。
```
