---
type: ADR
title: "ADR 0002: CLI and GUI Entrypoint Policy"
status: Accepted
timestamp: 2026-06-02
deciders: NEXTAltair
tags: [cli, gui-view, packaging]
depends_on: [pyside6, argparse]
---

# ADR 0002: CLI and GUI Entrypoint Policy

## Context

`tag-db` は引数なしで Qt GUI を起動していた。WSL、SSH、CI、サーバなどの headless 環境では、help を確認したいだけでも Qt 起動に進み、操作不能になる可能性がある。

## Decision

`tag-db` を CLI の正面入口にする。引数なしの `tag-db` は CLI help を表示し、GUI は `tag-db --gui` で明示起動する。

## Rationale

エージェントや CLI ユーザーは、まず `tag-db` や `tag-db --help` で利用可能なコマンドを探索する。別名の `tag-db-cli` へ分岐させるより、パッケージ名に近い `tag-db` を CLI 入口にする方が headless 環境で自然に使える。

## Consequences

既存の `tag-db` 単独 GUI 起動は `tag-db --gui` へ移行する必要がある。一方で CLI help は GUI 依存を import せずに表示でき、headless 環境での起動失敗を避けられる。
