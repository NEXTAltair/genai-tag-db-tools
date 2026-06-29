---
type: Reference
title: "Design: tag-db aliases register"
status: Implemented
timestamp: 2026-06-08
tags: [cli, db-write, tag-normalization, service-layer]
depends_on: [argparse, pydantic, sqlalchemy]
---

# Design: `tag-db aliases register` — 誤字alias一括登録CLI

**Issue:** NEXTAltair/genai-tag-db-tools#47  
**Date:** 2026-06-08  
**Status:** Approved

## 概要

`tag-db aliases register --file <path>` コマンドを追加し、JSONL/CSVで記述した誤字タグaliasをuser DBに一括登録できるようにする。

## アーキテクチャ

アプローチA: 既存の `TagRegisterService` に新メソッドを追加する。

```
CLI (cli.py)
  └─ cmd_aliases_register()
       └─ TagRegisterService.register_alias_entry(entry, dry_run)
            ├─ _resolve_format_id()   ← 既存ロジック再利用
            ├─ _resolve_type_id()     ← 既存ロジック再利用
            └─ TagRepository / MergedTagReader
```

## コンポーネント

### models.py — 新モデル3件

| モデル | 用途 |
|---|---|
| `AliasRegisterInput` | 1行の入力エントリ (alias / preferred / format_name / type_name) |
| `AliasRegisterItemResult` | 1行の処理結果 (status: would_create / created / skipped / conflict / missing_preferred) |
| `AliasRegisterResult` | 最終サマリ (ok / dry_run / total / created / skipped / conflicts / missing_preferred) |

### services/tag_register.py — 新メソッド

```python
def register_alias_entry(
    self,
    entry: AliasRegisterInput,
    dry_run: bool,
) -> AliasRegisterItemResult:
```

処理ロジック:
1. `preferred` タグをlookup → 見つからなければ `missing_preferred`
2. format/type を `_resolve_format_id` / `_resolve_type_id` で解決
3. `alias` タグのTAG_STATUSを `get_tag_status(alias_tag_id, format_id)` でlookup
4. STATUS存在 + `alias=True` + 同一`preferred_tag_id` → `skipped`
5. STATUS存在 + `alias=True` + 別`preferred_tag_id` → `conflict` (書き換えない)
6. `dry_run=True` → `would_create` (DB変更なし)
7. `dry_run=False` → create_tag + update_tag_status(alias=True) → `created`

### introspection.py

`TOOL_SPECS` に `"aliases/register"` を追加:
- `input_model=AliasRegisterInput`
- `output_model=AliasRegisterResult`
- `read_only=False`, `side_effects=("db_write",)`

### cli.py — 2階層サブコマンド

```
tag-db aliases register --file <path> [--apply] [--base-db ...] [--user-db-dir ...]
```

- `--apply`: 省略時はdry-run（デフォルト）
- `--file`: JSONL (.jsonl) または CSV (.csv) を拡張子で自動判定
- ファイルの各行を `AliasRegisterInput` にパース、`register_alias_entry()` を呼ぶ
- 各行を `emit_item()` で出力、最後に `emit_result()` でサマリ

出力例 (dry-run):
```jsonl
{"kind":"item","alias":"weding dress","preferred":"wedding dress","status":"would_create"}
{"kind":"result","ok":true,"dry_run":true,"total":1,"created":0,"skipped":0,"conflicts":0,"missing_preferred":0}
```

## エラーハンドリング

- ファイルが存在しない → `emit_error(INVALID_INPUT, ...)`
- 不正なJSONL行 → その行を `status="parse_error"` としてskipし続行
- DB接続エラー → 上位の `try/except` がキャッチ → `emit_error(INTERNAL_ERROR, ...)`

## テスト (tests/unit/test_cli_aliases_register.py)

| ケース | 検証内容 |
|---|---|
| dry_run / would_create | DB変更なし、status=would_create |
| apply / created | DB変更あり、status=created、tag_id返却 |
| skipped (already_exists) | 同一alias+preferred → status=skipped |
| conflict | alias存在+別preferred → status=conflict |
| missing_preferred | preferred未存在 → status=missing_preferred |
| CSV入力 | .csv拡張子で正しくパース |
| describe/list-commands | aliases/register がintrospectionに出る |

## 制約・非スコープ

- `update` (既存aliasの向き先変更) は本実装に含まない
- バルク入力の上限チェックは不要（ストリーム処理）
- JSONL入力の `format_name` / `type_name` はbase DB側に存在しなくても自動作成
