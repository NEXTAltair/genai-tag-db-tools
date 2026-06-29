---
type: ADR
title: "ADR 0005: CLI Command Introspection Contract"
status: Accepted
timestamp: 2026-06-02
deciders: NEXTAltair
tags: [cli, introspection]
depends_on: [pydantic]
---

# ADR 0005: CLI Command Introspection Contract

## Context

`tag-db --help` は人間向けで、エージェントやCIが各コマンドの入力モデル・出力モデル・副作用分類を機械的に取得できなかった。CLIの実行結果はADR 0003でJSONL化されたが、実行前に「このコマンドが何を受け取り、何を返し、何を書き込むか」を知る契約が未実装だった。

## Decision

`tag-db describe <command>` と `tag-db list-commands` を追加し、`tool` / `model` / `result` 行のJSONLで契約を返す。スキーマ本体はPydanticの `model_json_schema()` から生成し、CLI側でフィールド構造を手書き複製しない。

schema モードは **`compact`(既定)と `json_schema` の2つ**とする:

- `compact`: フィールドを簡易型表記(`str (required)` / `bool=true` / `int>=1?` / `list[str]?`)で `kind:"model"` 行に載せる。入れ子モデルは名前参照。人間にもエージェントにも読める既定形。
- `json_schema`: `model_json_schema()` の完全版。**この時のみ ADR 0003 の「stdout 全行 JSONL」の文書化された例外**とし、先頭に人間向け `#` note 1行 + 各モデルの生スキーマを1行JSONで出力する。

`describe` は input / output / error(`CliErrorResult`)の3ロールを返す。`list-commands` は `tool` 行 + `result` のみ(モデル行は出さない)。

## Rationale

`describe` / `list-commands` は Issue #32 とdocsで予定された名前で、通常コマンドと同じJSONL契約に乗せられる。compact 既定は生 JSON Schema より人間が読みやすく、エージェントも解釈できる(ADR 0003 の「行を浅く保つ + message」方針と整合)。完全版が必要な場面のために `json_schema` を用意するが、JSON Schema は深くネストし JSONL の浅い行方針と相容れないため、生スキーマ1行 + 人間向け note という割り切った例外形にする。当初案の `inline`/`ref`/`none` 3モードは、compact(=名前参照=ref 相当)+ json_schema(=完全展開)の2つで実用上十分なため簡素化した。

## Consequences

コマンドメタ定義はCLI introspectionの正本になるが、フィールドスキーマの正本は引き続き `models.py` のPydanticモデルである。既存モデルを持たなかった `convert` には `ConvertTagsRequest` / `ConvertTagsResult`、出力エラー契約には `CliErrorResult` を追加する。`--schema json_schema` は stdout 全行が kind 付き JSONL という不変条件の唯一の例外になる(docs/cli.md に明記)。`tool.read_only` は steady-state の分類であり、cold cache や `--user-db-dir` による条件付き副作用は既存CLI契約の注記に従う。
