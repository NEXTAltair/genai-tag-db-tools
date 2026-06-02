# ADR 0005: CLI Command Introspection Contract

- **日付**: 2026-06-02
- **ステータス**: Accepted

## Context

`tag-db --help` は人間向けで、エージェントやCIが各コマンドの入力モデル・出力モデル・副作用分類を機械的に取得できなかった。CLIの実行結果はADR 0003でJSONL化されたが、実行前に「このコマンドが何を受け取り、何を返し、何を書き込むか」を知る契約が未実装だった。

## Decision

`tag-db describe <command>` と `tag-db list-commands` を追加し、`tool` / `model` / `result` 行のJSONLで契約を返す。`--schema inline|ref|none` をサポートし、既定は自己完結する `inline` とする。スキーマ本体はPydanticの `model_json_schema()` から生成し、CLI側でフィールド構造を手書き複製しない。

## Rationale

`describe` と `list-commands` は既存docsとIssue #32で予定されていた名前で、通常コマンドと同じJSONL契約に乗せられる。既定を `inline` にすると1回の呼び出しでMCP移植やエージェント実行計画に必要な情報が揃う。出力量を抑えたい利用者には `ref` と `none` を残す。

## Consequences

コマンドメタ定義はCLI introspectionの正本になるが、フィールドスキーマの正本は引き続き `models.py` のPydanticモデルである。既存モデルを持たなかった `convert` には `ConvertTagsRequest` / `ConvertTagsResult` を追加し、出力エラー契約には `CliErrorResult` を追加する。`tool.read_only` はsteady-stateの分類であり、cold cacheや `--user-db-dir` による条件付き副作用は既存CLI契約の注記に従う。
