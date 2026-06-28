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

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        return self._tags.get(keyword)

    def get_format_id(self, format_name: str) -> int:
        result = {"Lorairo": 1001}.get(format_name)
        if result is None:
            raise ValueError(format_name)
        return result

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return 0 if type_name == "unknown" else None

    def get_tag_status(self, tag_id: int, format_id: int) -> DummyStatus | None:
        return self._statuses.get((tag_id, format_id))


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


class TestAliasesRegisterIntrospection:
    def test_aliases_register_appears_in_list_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        import argparse

        from genai_tag_db_tools.cli import cmd_list_commands

        cmd_list_commands(argparse.Namespace())
        output = capsys.readouterr().out
        lines = [json.loads(line) for line in output.splitlines() if line.strip()]
        tool_names = [line["name"] for line in lines if line.get("kind") == "tool"]
        assert "aliases/register" in tool_names

    def test_aliases_register_describe_outputs_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        import argparse

        from genai_tag_db_tools.cli import cmd_describe

        args = argparse.Namespace(target_command="aliases/register", schema="compact")
        cmd_describe(args)
        output = capsys.readouterr().out
        lines = [json.loads(line) for line in output.splitlines() if line.strip()]
        model_names = [line["name"] for line in lines if line.get("kind") == "model"]
        assert "AliasRegisterInput" in model_names
        assert "AliasRegisterResult" in model_names


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

    def _make_mock_service(self, status: str = "would_create") -> MagicMock:
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
            [
                {
                    "alias": "weding dress",
                    "preferred": "wedding dress",
                    "format_name": "Lorairo",
                    "type_name": "unknown",
                }
            ],
        )
        main(["aliases", "register", "--file", str(jsonl), "--base-db", str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        lines = [json.loads(line) for line in out.splitlines() if line.strip()]
        item = next(line for line in lines if line["kind"] == "item")
        result = next(line for line in lines if line["kind"] == "result")
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
            [
                {
                    "alias": "weding dress",
                    "preferred": "wedding dress",
                    "format_name": "Lorairo",
                    "type_name": "unknown",
                }
            ],
        )
        main(["aliases", "register", "--file", str(jsonl), "--apply", "--base-db", str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        lines = [json.loads(line) for line in out.splitlines() if line.strip()]
        result = next(line for line in lines if line["kind"] == "result")
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
            [
                {
                    "alias": "weding dress",
                    "preferred": "wedding dress",
                    "format_name": "Lorairo",
                    "type_name": "unknown",
                }
            ],
        )
        main(["aliases", "register", "--file", str(csv_file), "--base-db", str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        lines = [json.loads(line) for line in out.splitlines() if line.strip()]
        assert any(line["kind"] == "item" for line in lines)
        result = next(line for line in lines if line["kind"] == "result")
        assert result["total"] == 1

    def test_rejects_when_base_db_is_same_as_user_db(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--base-db が --user-db-dir/user_tags.sqlite と同一なら INVALID_INPUT で拒否 (Issue #49)。"""
        from genai_tag_db_tools.cli import main

        user_db = tmp_path / "user_tags.sqlite"
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "aliases",
                    "register",
                    "--file",
                    str(tmp_path / "dummy.jsonl"),
                    "--base-db",
                    str(user_db),
                    "--user-db-dir",
                    str(tmp_path),
                ]
            )
        assert exc_info.value.code == 2
        out = capsys.readouterr().out
        error_line = json.loads(out.strip())
        assert error_line["kind"] == "error"
        assert error_line["code"] == "INVALID_INPUT"
        assert error_line["user_action_required"] is True

    def test_allows_when_base_db_differs_from_user_db(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--base-db が user_tags.sqlite と別パスなら通常通り動作する (Issue #49)。"""
        from genai_tag_db_tools import cli
        from genai_tag_db_tools.cli import main

        mock_svc = self._make_mock_service("would_create")
        monkeypatch.setattr(cli, "_build_register_service", lambda: mock_svc)
        jsonl = self._make_jsonl_file(
            tmp_path,
            [
                {
                    "alias": "weding dress",
                    "preferred": "wedding dress",
                    "format_name": "Lorairo",
                    "type_name": "unknown",
                }
            ],
        )
        base_db = tmp_path / "base.sqlite"
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        main(
            [
                "aliases",
                "register",
                "--file",
                str(jsonl),
                "--base-db",
                str(base_db),
                "--user-db-dir",
                str(user_dir),
            ]
        )
        out = capsys.readouterr().out
        lines = [json.loads(line) for line in out.splitlines() if line.strip()]
        assert any(line["kind"] == "result" for line in lines)
