# ADR 0005: CLI Introspection (describe / list-commands)

- **日付**: 2026-06-02
- **ステータス**: Accepted

## Context

`tag-db` のコマンド仕様を取得する手段は argparse の `--help`(人間向けテキスト)のみで、引数の型・制約・戻り値の構造・副作用(read/write/network)を機械可読に取得できなかった。エージェントが CLI を自動で使うには、help テキストを解析するしかなかった。入出力契約の正本は `models.py` の Pydantic モデルに既にある(ADR 0003)。

## Decision

機械可読な introspection コマンドを追加する。

- `tag-db list-commands` — 全コマンドを 1 行 `kind:"tool"`(`name` / `message` / `read_only` / `side_effects` / `input_model` / `output_model`)+ 最終 `result` で出力。
- `tag-db describe <command>` — `kind:"tool"` + 入出力の `kind:"model"` + `result`。
- **schema モードは `compact`(既定)と `json_schema` の 2 つ**(当初案の `inline`/`ref`/`none` を置き換え):
  - `compact`: 簡易型表記(`str (required)` / `bool=true` / `int>=1?` / `list[str]?`)。入れ子モデルは名前参照。
  - `json_schema`: `model_json_schema()` の完全版。**この時のみ JSONL 単一形式(ADR 0003)の文書化された例外**とし、先頭に人間向け `#` note 1 行 + 各モデルの生スキーマを 1 行 JSON で出力する。
- スキーマは `models.py` の Pydantic から生成し手書き二重定義しない。`convert` の入出力も `ConvertRequest` / `ConvertResult` を追加して全コマンドをモデルで揃える(`stats` は意味的入力なしで `input_model=None`)。
- `side_effects` / `read_only` は docs/cli.md の steady-state 表に準拠。

## Rationale

`--help` の機械可読版を別出力で持つより、ADR 0003 の JSONL 契約に乗せた方が一貫する。compact 表記は生 JSON Schema より人間が読みやすく、エージェントも解釈できる。完全版が必要な場面のために `json_schema` を用意するが、JSON Schema は深くネストし JSONL の「行を浅く保つ」方針と相容れないため、生スキーマ 1 行 + 人間向け note という割り切った例外形にする。当初の `inline`/`ref`/`none` 3 モードは、compact(=名前参照=ref 相当)+ json_schema(=完全展開)の 2 つで実用上十分なため簡素化した。

## Consequences

エージェントが `list-commands` / `describe` で各コマンドの入出力・副作用・read-only を機械判定でき、将来の MCP 移植の土台になる。`--schema json_schema` は stdout 全行が kind 付き JSONL という不変条件の唯一の例外になる(docs/cli.md に明記)。`models.py` に `ConvertRequest` / `ConvertResult` が追加され `convert` の出力が機械可読契約に載る(出力キー `input`/`output`/`format` は後方互換)。`tools run` ディスパッチャと MCP サーバー本体はスコープ外。
