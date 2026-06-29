---
type: Contract
title: tag-db CLI Contract
status: Accepted
timestamp: 2026-06-29
tags: [cli, search, db-read, db-write, tag-conversion, recommendation, advisory, introspection]
depends_on: [pydantic, sqlalchemy, sqlite]
---

# tag-db CLI Contract

This document is the contract for the `tag-db` command-line interface. It is the
single reference for both agents and humans. The contract is intentionally small
and machine-readable so automation does not have to parse human-formatted text.

> Source of truth: the request/result shapes come from
> `src/genai_tag_db_tools/models.py` (Pydantic) and the `core_api` functions.
> The CLI is a thin JSONL wrapper over them and does not redefine the contract.

## Output format: JSONL only

- **stdout is JSONL**: one line is exactly one valid JSON object. There is no
  second human/agent output mode (no `--pretty`, no `--format`). Human
  readability is achieved by keeping each line shallow and one command =
  one responsibility, not by adding renderers.
- **stderr is for diagnostics**: logs, progress, and unexpected-error tracebacks
  go to stderr. stdout never contains color codes, progress bars, or decoration.
- **When a command runs, the final stdout line is always `result` or `error`**
  (including argparse input errors, which emit an `error` line + exit code 2).
- If JSONL feels hard to read, suspect the command is doing too much, not the
  output format.

### Scope: help is the documented exception

The JSONL `result` / `error` contract governs **command execution**. The launcher
meta operations are the explicit exception and print human-readable help to stdout
with exit code 0:

- `tag-db --help` / `tag-db -h`
- `tag-db` with no arguments (shows help; does not import the GUI)
- `tag-db --gui` launches the Qt GUI

Automation should invoke an explicit subcommand (`search` / `register` / ...);
those always follow the JSONL contract.

### Line kinds

| kind | When | Required fields |
|---|---|---|
| `item` | One record of a list-returning command (one record per line) | `kind`, plus the record fields |
| `event` | Optional progress | `kind`, `event`, `message` |
| `result` | Final line on success | `kind`, `ok:true`, `message`, plus command output |
| `error` | Final line on failure | `kind`, `ok:false`, `code`, `message`, `retryable`, `user_action_required` (optional `hint`, `details`) |

List-returning commands (`search`, `ensure-dbs`) emit one `item` line per record
and a final `result` line carrying a count summary. They never pack all records
into a single giant array line.

### Human-readable JSONL guidelines

- One line, one meaning. Keep the top level shallow.
- Every line carries a short `message`.
- Avoid deep nesting (`data.result.payload.metadata...` is not allowed).
- Split summary from detail; include `details` only when needed.

## Error contract

On failure the final stdout line is a structured `error` object. Failures are not
left as a bare traceback.

```json
{"kind": "error", "ok": false, "code": "PRECONDITION_FAILED", "message": "...", "retryable": false, "user_action_required": true, "hint": "..."}
```

### Standard error codes

`INVALID_INPUT`, `VALIDATION_FAILED`, `PRECONDITION_FAILED`, `NOT_FOUND`,
`ALREADY_EXISTS`, `CONFLICT`, `IO_ERROR`, `NETWORK_ERROR`, `DB_ERROR`,
`TIMEOUT`, `INTERNAL_ERROR`.

Exception → code mapping (see `src/genai_tag_db_tools/errors.py`):

| Exception | code |
|---|---|
| `ValueError` (e.g. bad source string, missing required arg) | `INVALID_INPUT` |
| pydantic `ValidationError` | `VALIDATION_FAILED` |
| `RuntimeError` (DB engine / user DB not initialized) | `PRECONDITION_FAILED` |
| `FileNotFoundError` / other `OSError` | `IO_ERROR` |
| Hugging Face / `requests` / `urllib3` errors | `NETWORK_ERROR` |
| SQLAlchemy errors | `DB_ERROR` |
| `TimeoutError` | `TIMEOUT` |
| anything else | `INTERNAL_ERROR` |

### Exit codes

| code | meaning |
|---|---|
| `0` | success |
| `2` | input / validation error (`INVALID_INPUT`, `VALIDATION_FAILED`) |
| `1` | runtime error (everything else) |

The full traceback for an unexpected `INTERNAL_ERROR` is written to stderr; stdout
stays JSONL-only.

## Side effects and read-only classification

The classification below is the **steady state** (base DBs already present, no
`--user-db-dir`). Two conditions add write/network side effects; see the notes.

| command | side effects (steady state) | read-only |
|---|---|---|
| `search` | `db_read` | conditional (see notes) |
| `stats` | `db_read` | conditional (see notes) |
| `convert` | `db_read` | conditional (see notes) |
| `recommend tag` | `db_read` | conditional (see notes) |
| `recommend translation` | none (pure compute) | yes |
| `recommend record` | `db_read` | yes |
| `register` | `db_write` | no |
| `ensure-dbs` | `network_read`, `file_write` | no |

> **Implicit base-DB downloads (cold cache):** when `--base-db` is omitted and the
> local cache is cold, *every* command — including `register` and the read
> commands — first calls `initialize_databases()`, which downloads the default
> Hugging Face base DBs and writes them to the cache (`network_read` +
> `file_write`) before doing its work. A failed download surfaces as a
> `NETWORK_ERROR` line. To stay read-only / offline, pre-provision the cache (e.g.
> `ensure-dbs`) or pass `--base-db`.
>
> **User-DB initialization (`--user-db-dir`):** passing `--user-db-dir` to *any*
> command (including the read commands) initializes the user DB — it creates the
> directory, runs the schema `create_all`, and inserts default format/type
> mappings (`file_write`). So `search` / `stats` / `convert` are read-only only
> when `--user-db-dir` is omitted (or points at an already-initialized user DB on
> a writable path). Do not point `--user-db-dir` at a read-only path for a read
> command.

## Non-interactive execution

All commands run without interactive prompts (no `Are you sure? [y/N]`).
Automation, CI, and scripts never block on input. Irreversible operations, if any
are added later, must require an explicit flag rather than prompting.

`register` writes to a user database. When `--user-db-dir` is omitted it falls
back to the OS-specific cache directory (consistent with the other commands), so
zero-config automation works; pass `--user-db-dir` to choose an explicit target.

## Commands

### search — read tags (`db_read`)

`search` returns at most `--limit` items (default **50**). Use `--limit 0` for
unlimited (opt-in). Each match is an `item` line; the final `result` carries the
counts. `--limit` / `--offset` are applied **after** post-filters (aliases,
deprecated, usage), so they count active results, not raw keyword matches.

> Cost note: `--limit` bounds the output, not the scan. A broad / near-empty
> partial query still materializes all keyword matches before filtering. Prefer
> specific queries. Repository-level bounding is tracked in issue #37.

```bash
tag-db search --query cat --limit 2
```

```jsonl
{"kind": "item", "tag": "cat", "source_tag": null, "tag_id": 1, "format_name": "danbooru", "type_id": 0, "type_name": "general", "alias": false, "deprecated": false, "usage_count": 12345, "translations": {}, "format_statuses": {}}
{"kind": "item", "tag": "cat_ears", "source_tag": null, "tag_id": 2, "format_name": "danbooru", "type_id": 0, "type_name": "general", "alias": false, "deprecated": false, "usage_count": 678, "translations": {}, "format_statuses": {}}
{"kind": "result", "ok": true, "message": "search completed", "query": "cat", "count": 2, "total": 2, "limit": 2, "offset": 0}
```

### register — add a tag (`db_write`)

```bash
tag-db register --tag mychar --format-name custom --type-name character
```

```jsonl
{"kind": "result", "ok": true, "message": "tag registered", "created": true, "tag_id": 1042}
```

### stats — summary statistics (`db_read`)

```bash
tag-db stats
```

```jsonl
{"kind": "result", "ok": true, "message": "statistics", "total_tags": 100000, "total_aliases": 2000, "total_formats": 5, "total_types": 10}
```

### convert — normalize tags to a format (`db_read`)

Output is always JSONL. `--json` is accepted but ignored (deprecated).

```bash
tag-db convert --tags "cat,1girl" --format-name danbooru
```

```jsonl
{"kind": "result", "ok": true, "message": "tags converted", "input": "cat,1girl", "output": "cat, 1girl", "format": "danbooru"}
```

### recommend tag — advisory refinement recommendation (`db_read`)

Advisory only: **read-only, non-blocking, never auto-replaces**. Evaluates whether
each tag needs manual refinement before registration and emits an `item` line per
tag (a `RefinementRecommendation`), then a final `result` with the counts. The
exit code is **always 0** on success even when tags need refinement — read
`needs_refinement` per item / `needs_refinement_count` on the result rather than
branching on the exit code.

Tags come from `--tag` (comma-separated and/or repeated), `--file` (one tag per
line), or stdin (one tag per line), resolved in that precedence. Reasons are
rule-based; when a base DB is present, alias / deprecated / preferred-status
reasons are added. With no DB hit it falls back to rule-only reasons. Pass
`--rule-only` to bypass DB initialization entirely and force the deterministic
`repo=None` path even when base DBs are installed.

```bash
tag-db recommend tag --tag "flower,1girl" --format-name danbooru
tag-db recommend tag --tag flower --rule-only
printf 'flower\n1girl\n' | tag-db recommend tag        # via stdin
```

```jsonl
{"kind": "item", "source_tag": "flower", "normalized_tag": "flower", "needs_refinement": true, "score": 0.5, "reasons": [{"code": "broad_single_word", "message": "...", "field": null, "evidence": []}], "suggestions": [{"kind": "review_only", "tag": null}], "proposals": []}
{"kind": "item", "source_tag": "1girl", "normalized_tag": "1girl", "needs_refinement": false, "score": 0.0, "reasons": [], "suggestions": [], "proposals": []}
{"kind": "result", "ok": true, "message": "recommendations completed", "total": 2, "needs_refinement_count": 1}
```

### recommend translation — advisory translation-quality recommendation (no DB)

Advisory only and **DB-independent** (pure compute, no side effects). Evaluates a
single `--source-tag` / `--translation` pair and emits the `RefinementRecommendation`
on the `result` line. Omit / empty `--translation` runs a missing-translation
check. Exit code is always 0 on success.

Pass `--target-scope {base,user}` and `--target-tag-id N` together to emit
target-scoped `translation_correction` proposals. Providing only one of the pair
is invalid input.

```bash
tag-db recommend translation --source-tag flower --translation "花" --language ja
tag-db recommend translation --source-tag flower --translation flower --language ja --target-scope user --target-tag-id 1000000001
```

```jsonl
{"kind": "result", "ok": true, "message": "translation recommendation", "source_tag": "flower", "normalized_tag": "flower", "needs_refinement": false, "score": 0.0, "reasons": [], "suggestions": [], "proposals": []}
```

### recommend record — advisory refinement recommendation for search records (`db_read`)

Consumes `tag-db search` JSONL from stdin and evaluates each `kind:"item"` row
with `recommend_tag_record_refinement`. `kind:"result"` and `kind:"event"` lines
are ignored; `kind:"error"` or invalid JSONL is invalid input. Each input item
emits one `RefinementRecommendation` `item`, followed by a final count `result`.

The default path uses the data already present in the search row and does not
initialize DBs again. `--base-db` / `--user-db-dir` may be provided when
repository metadata is needed.

```bash
tag-db search --query flower --limit 3 | tag-db recommend record --format-name danbooru
```

```jsonl
{"kind": "item", "source_tag": "flower", "normalized_tag": "flower", "needs_refinement": false, "score": 0.0, "reasons": [], "suggestions": [], "proposals": []}
{"kind": "result", "ok": true, "message": "record recommendations completed", "total": 1, "needs_refinement_count": 0}
```

### ensure-dbs — download base DBs (`network_read`, `file_write`)

```bash
tag-db ensure-dbs --source NEXTAltair/genai-image-tag-db/genai-image-tag-db-cc0.sqlite
```

```jsonl
{"kind": "item", "db_path": "/home/user/.cache/.../genai-image-tag-db-cc0.sqlite", "sha256": "...", "revision": null, "cached": true}
{"kind": "result", "ok": true, "message": "databases ensured", "count": 1}
```

### aliases register — bulk-register aliases (`db_write`)

Reads alias entries from a `.jsonl` / `.csv` file and registers them to the user
DB. **Dry-run by default**; pass `--apply` to write. Each entry is an `item` line
(`status`: `would_create` / `created` / `skipped` / `conflict` / `missing_preferred`)
and the final `result` carries the per-status counts.

```bash
tag-db aliases register --file aliases.jsonl          # dry-run
tag-db aliases register --file aliases.jsonl --apply   # write to user DB
```

```jsonl
{"kind": "item", "alias": "blakc_hair", "preferred": "black_hair", "format_name": "danbooru", "status": "would_create"}
{"kind": "result", "ok": true, "message": "dry-run complete", "dry_run": true, "total": 1, "created": 1, "skipped": 0, "conflicts": 0, "missing_preferred": 0}
```

### feedback — base DB correction patch pipeline

Validate / export / apply correction patches for the **base DB build sources**
(`#58` / `#60` / `#61`). These operate on JSONL patch files, not the live user DB.

- `feedback validate-base-patches --file <patch.jsonl>` — schema / scope / alias /
  type / translation の整合性を検証する（`db_read` 相当、副作用なし）。
- `feedback export-base-patches ...` — 承認済み feedback から base 用 correction patch
  JSONL を出力する（`file_write`）。
- `feedback apply-base-patches --file <patch.jsonl> --base-db <path> --apply` —
  validated patch を base DB build 出力へ適用する（`db_write`）。`--apply` 省略時は
  dry-run。`scope=user/local` や未承認・未検証の patch は拒否する。

```bash
tag-db feedback validate-base-patches --file patches.jsonl
tag-db feedback apply-base-patches --file patches.jsonl --base-db build/cc0.sqlite --apply
```

> Note: `aliases/register` は introspection registry (`TOOL_SPECS`) に登録済みで
> `list-commands` / `describe` に現れるが、**`feedback` 群は意図的に未登録**のため
> introspection には出ない。これは確定方針: introspection registry は **エージェントが
> 実行時に呼ぶ runtime コマンド面**（user DB への read/write・recommend）を公開する契約で、
> `feedback` 群は **base DB ビルド時の保守者/builder パイプライン**（JSONL patch ファイルの
> validate/export/apply、人間承認＋検証が前提）であり runtime のエージェント呼び出し対象では
> ないため除外する。詳細は ADR 0009（feedback routing）/ ADR 0005（introspection contract）。

## Introspection

`describe` and `list-commands` expose command contracts as machine-readable JSONL.
They do not initialize databases, access the network, or execute the described
command.

Default output is the compact type notation (`str (required)` / `bool=true` /
`int>=1?` / `list[str]?`; nested models are referenced by name). `describe`
returns input / output / error (`CliErrorResult`) model lines.

```bash
tag-db describe search
```

```jsonl
{"kind": "tool", "name": "search", "message": "Search tags (read-only).", "read_only": true, "side_effects": ["db_read"], "input_model": "TagSearchRequest", "output_model": "TagSearchResult", "error_model": "CliErrorResult"}
{"kind": "model", "role": "input", "name": "TagSearchRequest", "message": "input for search", "fields": {"query": "str (required)", "limit": "int>=1?", "format_names": "list[str]?", "offset": "int>=0"}}
{"kind": "model", "role": "output", "name": "TagSearchResult", "message": "output for search", "fields": {"items": "list[TagRecordPublic] (required)", "total": "int?"}}
{"kind": "result", "ok": true, "message": "command described", "command": "search"}
```

`list-commands` emits one `tool` line per command plus a final `result`:

```bash
tag-db list-commands
```

### `--schema` modes

- `compact` (default): short field notation per `model` line (human + agent readable).
- `json_schema`: the full Pydantic `model_json_schema()`. This mode is the **only**
  exception to "stdout is kind-tagged JSONL": the first line is a human `#` note,
  then each model's raw JSON Schema is emitted as one line.

```bash
tag-db describe search --schema json_schema
```

```
# Full JSON Schema (one model per line, raw model_json_schema; not kind-wrapped JSONL)
{"type": "object", "title": "TagSearchRequest", "properties": {"query": {"type": "string"}, ...}, "required": ["query"]}
{"type": "object", "title": "TagSearchResult", "properties": {...}}
{"type": "object", "title": "CliErrorResult", "properties": {...}}
```

The `tool.read_only` field is the steady-state classification. The conditional
cold-cache and `--user-db-dir` side effects described above still apply when the
actual command is executed.
