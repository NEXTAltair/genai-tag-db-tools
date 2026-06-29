---
type: Investigation
title: "Issue #63: tag-db CLI search/status output inconsistencies"
status: Accepted
timestamp: 2026-06-28
tags: [cli, search, db-read]
depends_on: [sqlalchemy, sqlite]
---

# Issue #63 — tag-db CLI search/status output inconsistencies

Status: investigated, one bug fixed, remaining items documented as expected behavior / doc-UX gaps.

## Scope

Investigate the odd-looking output of `tag-db search`, focusing on the relationship
between the **top-level** fields (`format_name`, `type_name`, `alias`, `deprecated`,
`usage_count`, `type_id`) and the per-format `format_statuses` map, especially when
`--format-name unknown` is used.

## How the search output is built (contract)

CLI `search` → `core_api.search_tags()` → `MergedTagReader.search_tags()` →
`TagReader.search_tags()` → `TagSearchQueryBuilder.filtered_tag_ids()` +
`TagSearchResultBuilder.build_row()`.

Key facts:

1. **Top-level `format_name` is an echo of the request, not derived from data.**
   `core_api.search_tags()` sets `format_name = format_names[0] if len(format_names) == 1 else None`
   (`src/genai_tag_db_tools/core_api.py:310`, used at `:349`). It documents *which*
   format the top-level status fields are meant to reflect. If you pass
   `--format-name unknown`, the top level always shows `format_name=unknown`, even
   though that string was never read back from the row.

2. **Top-level `type_name`/`alias`/`deprecated`/`usage_count`/`type_id` reflect a
   single "active" format.** `TagSearchResultBuilder._resolve_status_info()`
   (`src/genai_tag_db_tools/db/query_utils.py:558`) uses `self.format_id` — the id
   resolved from the requested format name — to pick the active status. When no single
   concrete format is requested (no `--format-name`, multiple formats, or `all`), there
   is no active format and the top-level status fields are intentionally left at their
   defaults (`type_name=""`, `alias=False`, `deprecated=False`, `usage_count=0`,
   `type_id=None`).

3. **`format_statuses` always lists every format the tag has a status in.**
   `TagSearchResultBuilder._build_format_statuses()`
   (`src/genai_tag_db_tools/db/query_utils.py:626`) iterates all statuses regardless of
   the requested format. This is why per-format `alias`/`deprecated`/`type_name` can
   differ across formats in the same result — that is real, per-booru data.

## Findings

### 1. BUG (fixed): `--format-name unknown` blanked the top-level type/status fields

Reproduced (real DB, after `uv run tag-db ensure-dbs`):

```
$ uv run tag-db search --query sorceress --format-name unknown --include-aliases --include-deprecated --limit 10
TOP:        type_name="",      type_id=null, usage_count=0
fs.unknown: type_name="unknown", type_id=0,  usage_count=1096310
```

Same for `bad id`, `commentary`, etc. The top-level fields were empty while
`format_statuses.unknown` was fully populated.

**Root cause.** The repository seeds a sentinel format named `unknown` with
**`format_id == 0`** (see `src/genai_tag_db_tools/db/runtime.py:149` and the type
mapping that pins `unknown` → `type_id=0`). Two places conflated that real format with
the "no active format" sentinel, because both used the integer `0`:

- `TagSearchQueryBuilder.filtered_tag_ids()` returned
  `format_id = format_ids[0] if len(format_ids) == 1 else 0`
  (`src/genai_tag_db_tools/db/query_utils.py:144`) — so a request for the real `unknown`
  format (id 0) was indistinguishable from "no format".
- `TagSearchResultBuilder._resolve_status_info()` guarded the active-status lookup with
  `if self.format_id:` (truthiness) — and `0` is falsy
  (`src/genai_tag_db_tools/db/query_utils.py:572`). So for `unknown`, the whole block was
  skipped and the defaults were returned.

The recommendation code path already worked around this (`_status_from_row_for_unknown_format`,
`_effective_recommendation_format_name` in `core_api.py`), but the plain `search` path
did not, leaving the inconsistent output the issue reported.

**Fix.** Use `None` (not `0`) as the "no single concrete format" sentinel, and test for
it explicitly so `format_id == 0` is treated as a real format:

- `filtered_tag_ids()` / `apply_format_filter()` now return `int | None` and yield `None`
  for the no-format / `all` / unresolved cases (`query_utils.py`).
- `TagSearchResultBuilder.format_id` is `int | None`; `_resolve_status_info()` and
  `_resolve_preferred_tag()` now test `if self.format_id is not None:`.

After the fix:

```
$ uv run tag-db search --query sorceress --format-name unknown ...
TOP:        type_name="unknown", type_id=0, usage_count=1096310   # matches fs.unknown
```

Regression test: `tests/unit/test_query_utils.py::test_filtered_tag_ids_unknown_format_returns_id_zero_not_none`
(plus the updated `test_filtered_tag_ids_treats_all_as_unfiltered`, which now asserts
`format_id is None` for `all`).

### 2. EXPECTED: top-level `format_name` echoes the request

`format_name=unknown` at the top level is by design (item 1 above). It is the label for
"which format do the top-level status fields describe", not a value read from the tag.
With the bug in finding 1 fixed, top-level `format_name=unknown` + `type_name=unknown`
are now internally consistent. No code change; documented here.

### 3. EXPECTED: per-format `alias`/`deprecated`/`type` differences

Example `nekomimi --format-name danbooru` shows `alias=true, deprecated=true` for
danbooru/e621/safebooru and `alias=false, deprecated=false` for derpibooru; `commentary`
shows `type_name` of `meta`/`general`/`unknown` across formats. This is genuine
per-booru data: a tag can be a deprecated alias in one booru and a canonical tag in
another. `format_statuses` is meant to expose exactly that. Not a bug.

### 4. EXPECTED (doc/UX gap): `pixiv` / `pixiv id` return 0 results under `--format-name unknown`

`--format-name unknown` filters to tags that have a status row **in the `unknown`
format**. `pixiv id` exists (in danbooru, safebooru, …) but has **no `unknown`-format
status**, so the `unknown` filter correctly returns 0:

```
$ uv run tag-db search --query "pixiv id" --format-name danbooru --exact ...
tag='pixiv id'  fmt keys=[danbooru, safebooru, ...]  has unknown = False   (count=1)

$ uv run tag-db search --query "pixiv id" --format-name unknown --exact ...
count=0
```

This is consistent with the format-filter semantics, not a bug. It is a UX gap: users
may not expect `--format-name unknown` to be a *restrictive* filter (only tags carrying
an `unknown`-format status), as opposed to "show me whatever, format-agnostic". The
`unknown` format is a sparse sentinel, so it legitimately returns far fewer tags than a
real booru. Recommendation: document that `--format-name unknown` matches only tags that
have an explicit `unknown`-format status, and that to search format-agnostically you
should omit `--format-name` entirely.

## Acceptance criteria coverage

- Why `--format-name unknown` top-level `type_name` was empty: explained (finding 1,
  the `format_id == 0` / truthiness conflation) and fixed.
- Relationship between top-level `format_name/type_name/alias/deprecated` and
  `format_statuses`: documented (contract section + findings 2–3).
- Bug fixed; non-bugs documented here.
- How to read `search` output for #56 real-data examples: use `format_statuses[<format>]`
  as the source of truth for per-format status; the top-level fields mirror the single
  format named by `--format-name` (now correct for `unknown` too), and are left at
  defaults when no single format is requested.

## Recommendation on #63

The concrete bug (finding 1) is fixed with tests. Findings 2–4 are expected behavior /
doc-UX. Suggest **closing #63** once this PR merges, optionally spinning off a small
follow-up doc/UX issue for finding 4 (clarify `--format-name unknown` filter semantics in
CLI help / docs) and, if desired, exposing a top-level field that makes "no active
format" explicit instead of relying on empty defaults.

## Commands run

```bash
uv run tag-db ensure-dbs                                   # succeeded (3 DBs)
uv run tag-db search --query sorceress  --format-name unknown  --include-aliases --include-deprecated --limit 10
uv run tag-db search --query nekomimi   --format-name danbooru --include-aliases --include-deprecated --limit 10
uv run tag-db search --query commentary --format-name unknown  --include-aliases --include-deprecated --limit 10
uv run tag-db search --query "pixiv id" --format-name unknown  --include-aliases --include-deprecated --exact --limit 5
uv run tag-db search --query "pixiv id" --format-name danbooru --include-aliases --include-deprecated --exact --limit 5
```
