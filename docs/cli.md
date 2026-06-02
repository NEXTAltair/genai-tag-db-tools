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

### ensure-dbs — download base DBs (`network_read`, `file_write`)

```bash
tag-db ensure-dbs --source NEXTAltair/genai-image-tag-db/genai-image-tag-db-cc0.sqlite
```

```jsonl
{"kind": "item", "db_path": "/home/user/.cache/.../genai-image-tag-db-cc0.sqlite", "sha256": "...", "revision": null, "cached": true}
{"kind": "result", "ok": true, "message": "databases ensured", "count": 1}
```

## Introspection

`describe` and `list-commands` expose command contracts as machine-readable JSONL.
They do not initialize databases, access the network, or execute the described
command.

```bash
tag-db describe search
```

```jsonl
{"kind": "tool", "name": "search", "description": "Search tags.", "side_effects": ["db_read"], "read_only": true, "input_model": "TagSearchRequest", "output_model": "TagSearchResult", "error_model": "CliErrorResult"}
{"kind": "model", "role": "input", "name": "TagSearchRequest", "version": "1", "schema_format": "inline", "schema": {"title": "TagSearchRequest", "type": "object", "properties": {}}}
{"kind": "model", "role": "output", "name": "TagSearchResult", "version": "1", "schema_format": "inline", "schema": {"title": "TagSearchResult", "type": "object", "properties": {}}}
{"kind": "model", "role": "error", "name": "CliErrorResult", "version": "1", "schema_format": "inline", "schema": {"title": "CliErrorResult", "type": "object", "properties": {}}}
{"kind": "result", "ok": true, "message": "command described", "command": "search", "schema": "inline"}
```

```bash
tag-db list-commands --schema none
```

`--schema` supports:

- `inline` (default): emit Pydantic `model_json_schema()` in `model` lines.
- `ref`: emit compact `#/models/<ModelName>` references instead of schema bodies.
- `none`: emit only `tool` lines and the final `result` line.

The `tool.read_only` field is the steady-state classification. The conditional
cold-cache and `--user-db-dir` side effects described above still apply when the
actual command is executed.
