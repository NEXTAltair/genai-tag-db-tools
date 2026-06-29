---
type: Plan
title: "aliases register Implementation Plan"
status: Implemented
timestamp: 2026-06-08
tags: [cli, db-write, tag-normalization, service-layer]
depends_on: [argparse, pydantic, sqlalchemy, polars]
---

# aliases register Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tag-db aliases register --file <path>` コマンドを追加し、JSONL/CSVで記述した誤字タグaliasをuser DBに一括登録する。

**Architecture:** 既存の `TagRegisterService` に `register_alias_entry()` メソッドを追加し、CLIから2階層サブコマンド `tag-db aliases register` で呼び出す。dry-run（デフォルト）と `--apply` でDB書き込みを制御する。

**Tech Stack:** Python 3.13, argparse, Pydantic v2, SQLAlchemy (TagStatus schema), polars (未使用だが既存依存)

---

## File Map

| ファイル | 変更種別 | 責務 |
|---|---|---|
| `src/genai_tag_db_tools/models.py` | Modify | 新モデル3件追加 |
| `src/genai_tag_db_tools/services/tag_register.py` | Modify | `register_alias_entry()` 追加 |
| `src/genai_tag_db_tools/introspection.py` | Modify | TOOL_SPECS に `aliases/register` 追加 |
| `src/genai_tag_db_tools/cli.py` | Modify | 2階層サブコマンド + `cmd_aliases_register` 追加 |
| `tests/unit/test_cli_aliases_register.py` | Create | 受け入れ条件テスト |

---

## Task 1: Pydanticモデル追加

**Files:**
- Modify: `src/genai_tag_db_tools/models.py`

- [ ] **Step 1: 既存テストを確認して壊れないことを把握する**

```bash
cd /workspaces/LoRAIro/local_packages/genai-tag-db-tools
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_models.py -v
```

Expected: 全テストPASS

- [ ] **Step 2: 3つのモデルを `models.py` 末尾に追加する**

`src/genai_tag_db_tools/models.py` のファイル末尾（`PreloadedData.model_rebuild()` の後）に追加:

```python
class AliasRegisterInput(BaseModel):
    """alias一括登録の1エントリ入力。"""

    alias: str = Field(..., description="エイリアスタグ（誤字・別名）")
    preferred: str = Field(..., description="正規タグ（preferred_tag）")
    format_name: str = Field(..., description="フォーマット名")
    type_name: str = Field(default="unknown", description="タイプ名")


class AliasRegisterItemResult(BaseModel):
    """alias登録の1行処理結果。"""

    alias: str = Field(..., description="エイリアスタグ")
    preferred: str = Field(..., description="正規タグ")
    status: str = Field(
        ...,
        description="処理結果: would_create / created / skipped / conflict / missing_preferred",
    )
    alias_tag_id: int | None = Field(default=None, description="aliasのタグID（apply後）")
    preferred_tag_id: int | None = Field(default=None, description="preferredのタグID")


class AliasRegisterResult(BaseModel):
    """alias一括登録の最終サマリ。"""

    ok: bool = Field(..., description="全体成功フラグ")
    dry_run: bool = Field(..., description="dry-runモードか")
    total: int = Field(..., description="入力行数")
    created: int = Field(..., description="新規作成件数")
    skipped: int = Field(..., description="スキップ件数（既存同一）")
    conflicts: int = Field(..., description="衝突件数")
    missing_preferred: int = Field(..., description="preferred未存在件数")
```

- [ ] **Step 3: モデルのインポートテストを実行する**

```bash
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run python -c "
from genai_tag_db_tools.models import AliasRegisterInput, AliasRegisterItemResult, AliasRegisterResult
print(AliasRegisterInput(alias='weding dress', preferred='wedding dress', format_name='Lorairo'))
print(AliasRegisterItemResult(alias='weding dress', preferred='wedding dress', status='would_create'))
print(AliasRegisterResult(ok=True, dry_run=True, total=1, created=0, skipped=0, conflicts=0, missing_preferred=0))
print('OK')
"
```

Expected: 3行の repr と "OK"

- [ ] **Step 4: コミット**

```bash
cd /workspaces/LoRAIro/local_packages/genai-tag-db-tools
git add src/genai_tag_db_tools/models.py
git commit -m "feat(models): AliasRegisterInput / ItemResult / Result 追加 (Issue #47)"
```

---

## Task 2: TagRegisterServiceに register_alias_entry() を追加

**Files:**
- Modify: `src/genai_tag_db_tools/services/tag_register.py`
- Test: `tests/unit/test_cli_aliases_register.py` (Task 5で作成するが、このタスクでDummyを先に書く)

- [ ] **Step 1: テストファイルを作成してDummyを書く（まだテストは書かない）**

`tests/unit/test_cli_aliases_register.py` を新規作成:

```python
"""Unit tests for `tag-db aliases register` command (Issue #47)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from genai_tag_db_tools.models import AliasRegisterInput
from genai_tag_db_tools.services.tag_register import TagRegisterService


class DummyStatus:
    def __init__(self, alias: bool, preferred_tag_id: int) -> None:
        self.alias = alias
        self.preferred_tag_id = preferred_tag_id


class DummyRepo:
    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.status_updates: list[dict] = []
        self._tag_ids: dict[str, int] = {}
        self._next_id = 100

    def create_tag(self, source_tag: str, tag: str) -> int:
        self.created_tags.append((source_tag, tag))
        new_id = self._next_id
        self._next_id += 1
        self._tag_ids[tag] = new_id
        return new_id

    def update_tag_status(
        self,
        tag_id: int,
        format_id: int,
        alias: bool,
        preferred_tag_id: int,
        type_id: int | None = None,
    ) -> None:
        self.status_updates.append(
            {"tag_id": tag_id, "format_id": format_id, "alias": alias, "preferred_tag_id": preferred_tag_id}
        )

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        pass

    def create_format_if_not_exists(
        self, format_name: str, description: str | None = None, reader: object = None
    ) -> int:
        return 1001

    def create_type_name_if_not_exists(self, type_name: str, description: str | None = None) -> int:
        return 0

    def get_next_type_id(self, format_id: int) -> int:
        return 1

    def create_type_format_mapping_if_not_exists(
        self, format_id: int, type_id: int, type_name_id: int, description: str | None = None
    ) -> int:
        return type_id


class DummyReader:
    def __init__(self) -> None:
        self._tags: dict[str, int] = {"wedding dress": 99}
        self._statuses: dict[tuple[int, int], DummyStatus] = {}

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self._tags.get(tag)

    def get_format_id(self, format_name: str) -> int:
        result = {"Lorairo": 1001}.get(format_name)
        if result is None:
            raise ValueError(format_name)
        return result

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return 0 if type_name == "unknown" else None

    def get_tag_status(self, tag_id: int, format_id: int) -> DummyStatus | None:
        return self._statuses.get((tag_id, format_id))
```

- [ ] **Step 2: 失敗するテストを1件書く (missing_preferred)**

`tests/unit/test_cli_aliases_register.py` の `DummyReader` クラスの後に追加:

```python
class TestRegisterAliasEntry:
    def _make_service(self, reader: DummyReader | None = None) -> TagRegisterService:
        repo = DummyRepo()
        r = reader or DummyReader()
        return TagRegisterService(repository=repo, reader=r)

    def test_missing_preferred_returns_missing_preferred_status(self) -> None:
        service = self._make_service()
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="nonexistent tag",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=True)
        assert result.status == "missing_preferred"
        assert result.alias == "weding dress"
        assert result.preferred == "nonexistent tag"
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
cd /workspaces/LoRAIro/local_packages/genai-tag-db-tools
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_cli_aliases_register.py::TestRegisterAliasEntry::test_missing_preferred_returns_missing_preferred_status -v
```

Expected: `AttributeError: 'TagRegisterService' object has no attribute 'register_alias_entry'`

- [ ] **Step 4: `register_alias_entry()` を `TagRegisterService` に実装する**

`src/genai_tag_db_tools/services/tag_register.py` の `TagRegisterService.register_tag()` メソッドの後（クラスの末尾）に追加:

```python
    def register_alias_entry(
        self,
        entry: "AliasRegisterInput",
        dry_run: bool,
    ) -> "AliasRegisterItemResult":
        """alias 1エントリを user DB に登録する（または dry-run で確認する）。

        Args:
            entry: 登録対象のaliasエントリ。
            dry_run: Trueの場合はDB変更を行わず would_create を返す。

        Returns:
            AliasRegisterItemResult: 処理結果。
        """
        from genai_tag_db_tools.models import AliasRegisterInput, AliasRegisterItemResult

        # 1. preferred タグを lookup
        preferred_tag_id = self._reader.get_tag_id_by_name(entry.preferred, partial=False)
        if preferred_tag_id is None:
            return AliasRegisterItemResult(
                alias=entry.alias,
                preferred=entry.preferred,
                status="missing_preferred",
            )

        # 2. format / type を解決
        fmt_id = self._resolve_format_id(entry.format_name)
        type_id = self._resolve_type_id(entry.type_name, entry.format_name, fmt_id)

        # 3. alias タグの既存チェック
        alias_tag_id = self._reader.get_tag_id_by_name(entry.alias, partial=False)
        if alias_tag_id is not None:
            status = self._reader.get_tag_status(alias_tag_id, fmt_id)
            if status is not None and status.alias:
                if status.preferred_tag_id == preferred_tag_id:
                    return AliasRegisterItemResult(
                        alias=entry.alias,
                        preferred=entry.preferred,
                        status="skipped",
                        alias_tag_id=alias_tag_id,
                        preferred_tag_id=preferred_tag_id,
                    )
                return AliasRegisterItemResult(
                    alias=entry.alias,
                    preferred=entry.preferred,
                    status="conflict",
                    alias_tag_id=alias_tag_id,
                    preferred_tag_id=preferred_tag_id,
                )

        # 4. dry_run モード: DB 変更なし
        if dry_run:
            return AliasRegisterItemResult(
                alias=entry.alias,
                preferred=entry.preferred,
                status="would_create",
                preferred_tag_id=preferred_tag_id,
            )

        # 5. 実際に作成
        new_alias_tag_id = self._repo.create_tag(entry.alias, entry.alias)
        self._repo.update_tag_status(
            tag_id=new_alias_tag_id,
            format_id=fmt_id,
            alias=True,
            preferred_tag_id=preferred_tag_id,
            type_id=type_id,
        )
        return AliasRegisterItemResult(
            alias=entry.alias,
            preferred=entry.preferred,
            status="created",
            alias_tag_id=new_alias_tag_id,
            preferred_tag_id=preferred_tag_id,
        )
```

また `services/tag_register.py` の `TYPE_CHECKING` ブロックを以下のように更新（既存の2行の後者を拡張）:

変更前:
```python
if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult
```

変更後:
```python
if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.models import AliasRegisterInput, AliasRegisterItemResult, TagRegisterRequest, TagRegisterResult
```

- [ ] **Step 5: テストをPASSさせて、残り4ケースを追加する**

```python
    def test_dry_run_returns_would_create(self) -> None:
        service = self._make_service()
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=True)
        assert result.status == "would_create"
        assert result.preferred_tag_id == 99

    def test_apply_returns_created_and_writes_db(self) -> None:
        repo = DummyRepo()
        service = TagRegisterService(repository=repo, reader=DummyReader())
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=False)
        assert result.status == "created"
        assert result.alias_tag_id is not None
        assert result.preferred_tag_id == 99
        assert len(repo.status_updates) == 1
        assert repo.status_updates[0]["alias"] is True
        assert repo.status_updates[0]["preferred_tag_id"] == 99

    def test_skipped_when_same_preferred_exists(self) -> None:
        reader = DummyReader()
        reader._tags["weding dress"] = 200
        reader._statuses[(200, 1001)] = DummyStatus(alias=True, preferred_tag_id=99)
        service = self._make_service(reader=reader)
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=False)
        assert result.status == "skipped"

    def test_conflict_when_different_preferred_exists(self) -> None:
        reader = DummyReader()
        reader._tags["weding dress"] = 200
        reader._tags["other dress"] = 300
        reader._statuses[(200, 1001)] = DummyStatus(alias=True, preferred_tag_id=300)
        service = self._make_service(reader=reader)
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=False)
        assert result.status == "conflict"
```

- [ ] **Step 6: テストをすべて実行して確認する**

```bash
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_cli_aliases_register.py::TestRegisterAliasEntry -v
```

Expected: 5件すべてPASS

- [ ] **Step 7: コミット**

```bash
git add src/genai_tag_db_tools/services/tag_register.py tests/unit/test_cli_aliases_register.py
git commit -m "feat(service): TagRegisterService.register_alias_entry() 追加 (Issue #47)"
```

---

## Task 3: introspectionに aliases/register を追加

**Files:**
- Modify: `src/genai_tag_db_tools/introspection.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_cli_aliases_register.py` の末尾に追加:

```python
class TestAliasesRegisterIntrospection:
    def test_aliases_register_appears_in_list_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        from genai_tag_db_tools.cli import cmd_list_commands
        import argparse
        cmd_list_commands(argparse.Namespace())
        output = capsys.readouterr().out
        lines = [json.loads(line) for line in output.splitlines() if line.strip()]
        tool_names = [l["name"] for l in lines if l.get("kind") == "tool"]
        assert "aliases/register" in tool_names

    def test_aliases_register_describe_outputs_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        from genai_tag_db_tools.cli import cmd_describe
        import argparse
        args = argparse.Namespace(target_command="aliases/register", schema="compact")
        cmd_describe(args)
        output = capsys.readouterr().out
        lines = [json.loads(line) for line in output.splitlines() if line.strip()]
        model_names = [l["name"] for l in lines if l.get("kind") == "model"]
        assert "AliasRegisterInput" in model_names
        assert "AliasRegisterResult" in model_names
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_cli_aliases_register.py::TestAliasesRegisterIntrospection -v
```

Expected: `AssertionError: assert 'aliases/register' in [...]`

- [ ] **Step 3: introspection.py を修正する**

`src/genai_tag_db_tools/introspection.py` のimportブロックを更新:

```python
from genai_tag_db_tools.models import (
    AliasRegisterInput,
    AliasRegisterResult,
    CliErrorResult,
    ConvertTagsRequest,
    ConvertTagsResult,
    EnsureDbRequest,
    EnsureDbResult,
    TagRegisterRequest,
    TagRegisterResult,
    TagSearchRequest,
    TagSearchResult,
    TagStatisticsResult,
)
```

`TOOL_SPECS` dict の末尾（`"convert"` エントリの後）に追加:

```python
    "aliases/register": ToolSpec(
        name="aliases/register",
        description="Bulk-register typo alias entries to user DB (dry-run by default).",
        side_effects=("db_write",),
        read_only=False,
        input_model=AliasRegisterInput,
        output_model=AliasRegisterResult,
    ),
```

- [ ] **Step 4: テストをPASSさせる**

```bash
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_cli_aliases_register.py::TestAliasesRegisterIntrospection -v
```

Expected: 2件PASS

- [ ] **Step 5: コミット**

```bash
git add src/genai_tag_db_tools/introspection.py tests/unit/test_cli_aliases_register.py
git commit -m "feat(introspection): aliases/register を TOOL_SPECS に追加 (Issue #47)"
```

---

## Task 4: CLI サブコマンド aliases register を追加

**Files:**
- Modify: `src/genai_tag_db_tools/cli.py`

- [ ] **Step 1: 失敗するCLIテストを書く**

`tests/unit/test_cli_aliases_register.py` の末尾に追加:

```python
class TestCmdAliasesRegister:
    def _make_jsonl_file(self, tmp_path: Path, lines: list[dict]) -> Path:
        f = tmp_path / "aliases.jsonl"
        f.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
        return f

    def _make_csv_file(self, tmp_path: Path, rows: list[dict]) -> Path:
        import csv
        f = tmp_path / "aliases.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["alias", "preferred", "format_name", "type_name"])
            writer.writeheader()
            writer.writerows(rows)
        return f

    @pytest.fixture(autouse=True)
    def _patch_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from genai_tag_db_tools import cli
        monkeypatch.setattr(cli, "_set_db_paths", lambda *a, **kw: None)

    def _make_mock_service(self, status: str = "would_create", dry_run_result: bool = True) -> MagicMock:
        from genai_tag_db_tools.models import AliasRegisterItemResult
        svc = MagicMock()
        svc.register_alias_entry.return_value = AliasRegisterItemResult(
            alias="weding dress",
            preferred="wedding dress",
            status=status,
            alias_tag_id=100 if status == "created" else None,
            preferred_tag_id=99,
        )
        return svc

    def test_dry_run_default_outputs_would_create(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from genai_tag_db_tools import cli
        from genai_tag_db_tools.cli import main
        mock_svc = self._make_mock_service("would_create")
        monkeypatch.setattr(cli, "_build_register_service", lambda: mock_svc)
        jsonl = self._make_jsonl_file(
            tmp_path,
            [{"alias": "weding dress", "preferred": "wedding dress", "format_name": "Lorairo", "type_name": "unknown"}],
        )
        main(["aliases", "register", "--file", str(jsonl), "--base-db", str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        lines = [json.loads(l) for l in out.splitlines() if l.strip()]
        item = next(l for l in lines if l["kind"] == "item")
        result = next(l for l in lines if l["kind"] == "result")
        assert item["status"] == "would_create"
        assert result["dry_run"] is True
        assert result["total"] == 1

    def test_apply_flag_sets_dry_run_false(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from genai_tag_db_tools import cli
        from genai_tag_db_tools.cli import main
        mock_svc = self._make_mock_service("created")
        monkeypatch.setattr(cli, "_build_register_service", lambda: mock_svc)
        jsonl = self._make_jsonl_file(
            tmp_path,
            [{"alias": "weding dress", "preferred": "wedding dress", "format_name": "Lorairo", "type_name": "unknown"}],
        )
        main(["aliases", "register", "--file", str(jsonl), "--apply", "--base-db", str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        lines = [json.loads(l) for l in out.splitlines() if l.strip()]
        result = next(l for l in lines if l["kind"] == "result")
        assert result["dry_run"] is False
        call_args = mock_svc.register_alias_entry.call_args
        assert call_args.kwargs["dry_run"] is False

    def test_csv_input_parsed_correctly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from genai_tag_db_tools import cli
        from genai_tag_db_tools.cli import main
        mock_svc = self._make_mock_service("would_create")
        monkeypatch.setattr(cli, "_build_register_service", lambda: mock_svc)
        csv_file = self._make_csv_file(
            tmp_path,
            [{"alias": "weding dress", "preferred": "wedding dress", "format_name": "Lorairo", "type_name": "unknown"}],
        )
        main(["aliases", "register", "--file", str(csv_file), "--base-db", str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        lines = [json.loads(l) for l in out.splitlines() if l.strip()]
        assert any(l["kind"] == "item" for l in lines)
        result = next(l for l in lines if l["kind"] == "result")
        assert result["total"] == 1
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_cli_aliases_register.py::TestCmdAliasesRegister -v
```

Expected: `SystemExit` または argparse error（`aliases` が未知のサブコマンド）

- [ ] **Step 3: cli.py に `_parse_alias_file()` と `cmd_aliases_register()` と `aliases` サブコマンドを追加する**

`src/genai_tag_db_tools/cli.py` に以下を追加する。

**3a. 既存importに追加**（ファイル先頭の `import json` 行の下に `import csv` を追加）:

```python
import csv
```

**3b. `cmd_stats()` の後に新関数2件を追加**:

```python
def _parse_alias_file(file_path: "Path") -> "list[AliasRegisterInput]":
    """JSONL または CSV から AliasRegisterInput のリストを返す。"""
    import csv as _csv
    import json as _json
    from pathlib import Path as _Path

    from genai_tag_db_tools.models import AliasRegisterInput

    path = _Path(file_path)
    entries: list[AliasRegisterInput] = []

    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8", newline="") as fh:
            reader = _csv.DictReader(fh)
            for row in reader:
                entries.append(
                    AliasRegisterInput(
                        alias=row["alias"],
                        preferred=row["preferred"],
                        format_name=row["format_name"],
                        type_name=row.get("type_name") or "unknown",
                    )
                )
    else:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = _json.loads(line)
                entries.append(AliasRegisterInput(**data))

    return entries


def cmd_aliases_register(args: argparse.Namespace) -> None:
    """aliases register サブコマンドのハンドラ。"""
    if args.user_db_dir:
        user_db_dir = args.user_db_dir
    else:
        from genai_tag_db_tools.io.hf_downloader import default_cache_dir

        user_db_dir = str(default_cache_dir())

    _set_db_paths(args.base_db, user_db_dir)
    service = _build_register_service()
    dry_run = not args.apply

    entries = _parse_alias_file(args.file)

    total = created = skipped = conflicts = missing_preferred = 0
    for entry in entries:
        total += 1
        item_result = service.register_alias_entry(entry, dry_run=dry_run)
        emit_item(item_result)
        if item_result.status in ("would_create", "created"):
            created += 1
        elif item_result.status == "skipped":
            skipped += 1
        elif item_result.status == "conflict":
            conflicts += 1
        elif item_result.status == "missing_preferred":
            missing_preferred += 1

    emit_result(
        "dry-run complete" if dry_run else "aliases registered",
        dry_run=dry_run,
        total=total,
        created=created,
        skipped=skipped,
        conflicts=conflicts,
        missing_preferred=missing_preferred,
    )
```

**3c. `build_parser()` の `list_commands_parser.set_defaults(...)` の直前に `aliases` サブコマンドを追加**:

```python
    aliases_parser = subparsers.add_parser("aliases", help="Manage tag aliases.")
    aliases_subs = aliases_parser.add_subparsers(dest="aliases_command", required=True)

    aliases_register_parser = aliases_subs.add_parser(
        "register",
        help="Bulk-register alias entries from JSONL/CSV file (dry-run by default).",
    )
    aliases_register_parser.add_argument(
        "--file",
        required=True,
        help="Input file path (.jsonl or .csv).",
    )
    aliases_register_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write to user DB. Omit for dry-run (default).",
    )
    _add_base_db_args(aliases_register_parser)
    aliases_register_parser.set_defaults(func=cmd_aliases_register)
```

**3d. `describe_parser` の `choices` も更新が必要**。`build_parser` 内の describe_parser 追加部分を確認する:

```python
    describe_parser.add_argument("target_command", choices=[spec.name for spec in iter_tool_specs()])
```

この行は `iter_tool_specs()` を動的に呼ぶので、`TOOL_SPECS` に `aliases/register` を追加済みであれば自動的に含まれる。変更不要。

- [ ] **Step 4: テストをPASSさせる**

```bash
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest tests/unit/test_cli_aliases_register.py::TestCmdAliasesRegister -v
```

Expected: 3件PASS

- [ ] **Step 5: コミット**

```bash
git add src/genai_tag_db_tools/cli.py tests/unit/test_cli_aliases_register.py
git commit -m "feat(cli): tag-db aliases register サブコマンド追加 (Issue #47)"
```

---

## Task 5: 全テストスイートを実行してCI-equivalent passを確認

- [ ] **Step 1: genai-tag-db-tools のCI filterで全件実行する**

```bash
cd /workspaces/LoRAIro/local_packages/genai-tag-db-tools
UV_PROJECT_ENVIRONMENT=/workspaces/LoRAIro/.venv uv run pytest -m "not slow and not network" -v 2>&1 | tail -30
```

Expected: 全件PASS (新規5件以上が追加されている)

- [ ] **Step 2: mypy でtype checkを確認する**

```bash
cd /workspaces/LoRAIro
uv run mypy -p genai_tag_db_tools 2>&1 | tail -20
```

Expected: `Success: no issues found` または既存のエラーのみ（新規エラーなし）

- [ ] **Step 3: ruff でlintを確認する**

```bash
cd /workspaces/LoRAIro
uv run ruff check local_packages/genai-tag-db-tools/src/ local_packages/genai-tag-db-tools/tests/ 2>&1 | tail -20
```

Expected: エラーなし

- [ ] **Step 4: 最終コミット（必要なら修正後）**

```bash
cd /workspaces/LoRAIro/local_packages/genai-tag-db-tools
git add -p  # 修正があれば
git commit -m "fix: mypy/ruff修正 (Issue #47)" || echo "no changes"
```

---

## Task 6: PR作成

- [ ] **Step 1: ブランチをpushしてPRを起票する**

```bash
cd /workspaces/LoRAIro/local_packages/genai-tag-db-tools
git push origin HEAD
gh pr create \
  --title "feat(cli): tag-db aliases register — 誤字alias一括登録コマンド (Issue #47)" \
  --body "$(cat <<'EOF'
## Summary

- `tag-db aliases register --file <path>` サブコマンドを追加
- JSONL/CSV形式でaliasエントリを一括登録
- `--apply` なし（デフォルト）は dry-run、`--apply` 付きでDB書き込み
- conflict / skipped / missing_preferred を JSONL で報告
- `describe` / `list-commands` の introspection に `aliases/register` を追加

## Test plan

- [ ] `pytest tests/unit/test_cli_aliases_register.py` でサービス・CLI・introspection 全件PASS
- [ ] `pytest -m "not slow and not network"` で既存テスト regression なし
- [ ] mypy / ruff エラーなし

Closes #47

🤖 Generated with [Claude Code](https://claude.ai/claude-code)
EOF
)"
```

---

## 注意事項

- `TagStatus.preferred_tag_id` は SQLAlchemy schema上 `int` (NOT NULL) だが、`non-alias` の場合は `tag_id` 自身を指すConstraint (`ck_preferred_tag_consistency`) がある。alias登録では `preferred_tag_id != tag_id` を必ず満たすこと。
- `_resolve_format_id` は format が存在しない場合に自動作成するため、`dry_run=True` の場合でもformat/typeのDB書き込みが発生する。Issue #47の責務定義で許容されている（format/type作成はalias保存の前提）。
- `DummyReader.get_format_id` は `ValueError` を raise する必要があるが、Pythonでは `dict.get()` に `raise` を inline で書けないため、次のように書くこと:
  ```python
  def get_format_id(self, format_name: str) -> int:
      result = {"Lorairo": 1001}.get(format_name)
      if result is None:
          raise ValueError(format_name)
      return result
  ```
