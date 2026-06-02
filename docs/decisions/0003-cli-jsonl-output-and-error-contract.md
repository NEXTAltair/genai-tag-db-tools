# ADR 0003: CLI JSONL Output and Structured Error Contract

- **日付**: 2026-06-02
- **ステータス**: Accepted

## Context

`tag-db` CLI の出力は `json.dumps(indent=2)` の pretty JSON 1 ブロックで、`convert` だけ素テキストと不統一だった。失敗時は例外が素通りして traceback が stderr に出るだけで、入力エラーと実行エラーが exit code で区別できなかった。エージェント・スクリプト・CI が結果を機械判定しづらく、人間向け・エージェント向けで出力を分けると drift する。

## Decision

機械可読出力を **JSONL 単一形式**に統一する。

- **stdout は JSONL 専用**(1 行 = 1 つの valid JSON オブジェクト)。`--pretty` / `--format` のような二重出力は持たない。
- 行種別を `item` / `event` / `result` / `error` とし、**コマンド実行時の最終行は必ず `result` か `error`**。list を返すコマンド(`search` / `ensure-dbs`)は 1 レコード = 1 行で出し、最終 `result` に件数 summary を置く。
- ログ・進捗・予期しない traceback は **stderr** へ。
- 失敗は stdout 最終行の構造化 `error`(`code` / `message` / `retryable` / `user_action_required` + 任意 `hint`)へマッピングする。**標準エラーコード集合**(`INVALID_INPUT` / `VALIDATION_FAILED` / `PRECONDITION_FAILED` / `NOT_FOUND` / `ALREADY_EXISTS` / `CONFLICT` / `IO_ERROR` / `NETWORK_ERROR` / `DB_ERROR` / `TIMEOUT` / `INTERNAL_ERROR`)を定義。
- **exit code 方針**: 0 成功 / 2 入力・バリデーション / 1 実行時。argparse の入力エラーも error 行 + exit 2 にする。
- 契約の SSoT は `models.py`(Pydantic)+ `core_api`。CLI は薄い JSONL ラッパーとし二重定義しない。
- 全コマンドは非対話で完走する。`register` は `--user-db-dir` 未指定時に既定キャッシュへフォールバックしゼロコンフィグで動く。
- `--help` / `-h` / 引数なし help は人間向け help を stdout(exit 0)で返す文書化された例外(JSONL 契約はコマンド実行時のもの)。

詳細仕様は [docs/cli.md](../cli.md)。

## Rationale

「機械可読」と「人間可読」を別出力で分けると必ず drift する。JSONL は 1 行 1 意味で grep/jq とも相性が良く、人間可読性は「行を浅く保つ」「1 コマンド 1 責務」で担保できる。エラーを stderr 文字列パースに依存させず stdout の構造化行へ出すことで、エージェントが機械判定でき人間も理由を読める。標準エラーコードと exit code を固定すると、将来 MCP 等へ移植する際の土台にもなる。

## Consequences

既存 5 コマンドの出力が JSONL に統一され `convert` の不統一が解消する。引数・サブコマンド名は後方互換。`convert --json` は deprecated no-op として受理。`search` は既定 `--limit 50`(`--limit 0` で無制限)を持つ。CLI 境界で broad な `except` を 1 箇所だけ許容する(例外を error 行へ変換する正当な責務)。introspection(機械可読な `describe`)は本 ADR の範囲外で未実装。
