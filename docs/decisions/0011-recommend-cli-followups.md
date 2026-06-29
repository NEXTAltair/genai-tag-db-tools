---
type: ADR
title: "ADR 0011: Recommendation CLI Follow-up Adapters"
status: Accepted
timestamp: 2026-06-29
deciders: NEXTAltair
tags: [cli, recommendation, advisory, introspection]
depends_on: [argparse, pydantic]
---

# ADR 0011: Recommendation CLI Follow-up Adapters

## Context

Issue #102 exposed `recommend tag` and `recommend translation` as thin CLI
adapters over the recommendation public API. Issue #105 adds the deferred pieces:
record-level recommendations from `search` JSONL, target-scoped translation
proposals, and deterministic rule-only tag checks even when base DBs are present.

These commands are advisory and must remain read-only. The CLI should not
reimplement recommendation logic that already lives in `core_api`.

## Decision

- `recommend tag --rule-only` bypasses DB initialization and calls
  `recommend_manual_refinement(..., repo=None)`.
- `recommend translation` accepts `--target-scope {base,user}` with
  `--target-tag-id`; the pair is validated together and forwarded to
  `recommend_translation_quality`.
- `recommend record` reads JSONL from stdin, processes only `kind:"item"` rows,
  rejects `kind:"error"` or invalid rows, and emits one `RefinementRecommendation`
  `item` per input row plus a final count `result`.
- `recommend/record` is registered in CLI introspection with `db_read` side
  effects because it may initialize a reader for format metadata.

## Rationale

`--rule-only` is an explicit escape hatch for deterministic checks and CI smoke
tests; it avoids hidden HF cache/network behavior while preserving the existing
DB-backed default. Target-scoped translation arguments expose existing core API
proposal behavior without inventing CLI-side proposal construction. JSONL stdin
for `recommend record` keeps the command composable with `tag-db search` and
preserves the one-record-per-line CLI contract.

## Consequences

- `recommend tag --tag flower` can still return no refinement when the DB has a
  valid exact tag, while `--rule-only` returns rule-based broad-word advisory
  output.
- Consumers can pipe `search` into `recommend record` without parsing arrays.
- Docs, CLI tests, and introspection tests must stay aligned with the three
  recommendation subcommands.
