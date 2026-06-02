"""Unit tests for CLI helper functions.

Tests cover:
- _parse_source: Source string parsing
- _dump: JSON output formatting
- _build_cache_config: Configuration building
- _set_db_paths: Database path setup
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

import genai_tag_db_tools.cli as cli
from genai_tag_db_tools.cli import (
    ParsedSource,
    _build_cache_config,
    _parse_source,
    _set_db_paths,
    emit_event,
    emit_item,
    emit_result,
    main,
)
from genai_tag_db_tools.db import runtime


class TestParseSource:
    """Test _parse_source function."""

    def test_parse_source_with_revision(self) -> None:
        """repo_id/filename@revision形式のパース成功"""
        result = _parse_source("deepghs/site-tags/tags_v3.db@main")
        assert result == ParsedSource(repo_id="deepghs/site-tags", filename="tags_v3.db", revision="main")

    def test_parse_source_without_revision(self) -> None:
        """repo_id/filename形式（revision省略）のパース成功"""
        result = _parse_source("deepghs/site-tags/tags_v3.db")
        assert result == ParsedSource(repo_id="deepghs/site-tags", filename="tags_v3.db", revision=None)

    def test_parse_source_with_nested_path(self) -> None:
        """ネストしたrepo_idのパース成功"""
        result = _parse_source("org/user/repo/data.db@v1.0")
        assert result == ParsedSource(repo_id="org/user/repo", filename="data.db", revision="v1.0")

    def test_parse_source_no_slash_raises_error(self) -> None:
        """スラッシュなしの入力でエラー"""
        with pytest.raises(ValueError, match="source must be repo_id/filename"):
            _parse_source("invalid_source")

    def test_parse_source_empty_repo_id_raises_error(self) -> None:
        """空のrepo_idでエラー"""
        with pytest.raises(ValueError, match="source must be repo_id/filename"):
            _parse_source("/filename.db")

    def test_parse_source_empty_filename_raises_error(self) -> None:
        """空のfilenameでエラー"""
        with pytest.raises(ValueError, match="source must be repo_id/filename"):
            _parse_source("repo_id/")


class TestEmitters:
    """Test JSONL emitter functions (emit_result / emit_item / emit_event)."""

    def test_emit_result_is_single_jsonl_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        """emit_result は kind=result の 1 行 JSONL を出力する"""
        emit_result("done", count=3)

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"kind": "result", "ok": True, "message": "done", "count": 3}

    def test_emit_item_wraps_pydantic_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        """emit_item は Pydantic model を kind=item の 1 行で平坦に出力する"""

        class Item(BaseModel):
            id: int
            label: str

        emit_item(Item(id=1, label="first"))

        output = json.loads(capsys.readouterr().out)
        assert output == {"kind": "item", "id": 1, "label": "first"}

    def test_emit_item_non_dict_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        """dict 化できない値は value キーに包む"""
        emit_item("plain_string")

        output = json.loads(capsys.readouterr().out)
        assert output == {"kind": "item", "value": "plain_string"}

    def test_emit_event(self, capsys: pytest.CaptureFixture[str]) -> None:
        """emit_event は kind=event の進捗行を出力する"""
        emit_event("progress", "halfway")

        output = json.loads(capsys.readouterr().out)
        assert output == {"kind": "event", "event": "progress", "message": "halfway"}

    def test_emit_ensures_ascii_false(self, capsys: pytest.CaptureFixture[str]) -> None:
        """日本語文字列が Unicode escape されずに出力される"""
        emit_result("テスト")

        out = capsys.readouterr().out
        assert "テスト" in out
        assert "\\u" not in out


class TestBuildCacheConfig:
    """Test _build_cache_config function."""

    def test_build_cache_config_with_user_db_dir(self) -> None:
        """user_db_dir指定時のDbCacheConfig生成"""
        args = argparse.Namespace(user_db_dir="/custom/path", token="test_token")
        config = _build_cache_config(args)

        assert config.cache_dir == "/custom/path"
        assert config.token == "test_token"

    def test_build_cache_config_without_user_db_dir(self) -> None:
        """user_db_dir未指定時のデフォルトキャッシュディレクトリ使用"""
        args = argparse.Namespace(token="test_token")
        config = _build_cache_config(args)

        # デフォルトキャッシュディレクトリが設定される
        assert config.cache_dir is not None
        assert len(config.cache_dir) > 0
        assert config.token == "test_token"

    def test_build_cache_config_without_token(self) -> None:
        """token未指定時のNone設定"""
        args = argparse.Namespace(user_db_dir="/path")
        config = _build_cache_config(args)

        assert config.cache_dir == "/path"
        assert config.token is None


class TestSetDbPaths:
    """Test _set_db_paths function."""

    def _mock_default_bases(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from genai_tag_db_tools.models import EnsureDbResult

        db_paths = []
        for filename in (
            "genai-image-tag-db-cc4.sqlite",
            "genai-image-tag-db-mit.sqlite",
            "genai-image-tag-db-cc0.sqlite",
        ):
            path = tmp_path / filename
            path.touch()
            db_paths.append(path)

        results = [
            EnsureDbResult(db_path=str(path), sha256="mock", revision=None, cached=True)
            for path in db_paths
        ]

        monkeypatch.setattr("genai_tag_db_tools.cli.initialize_databases", lambda **_kwargs: results)

    def test_set_db_paths_both_specified(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """base_db_pathsとuser_db_dirの両方指定"""
        base_path1 = tmp_path / "base1.db"
        base_path2 = tmp_path / "base2.db"
        user_dir = tmp_path / "user_db"

        base_path1.touch()
        base_path2.touch()
        user_dir.mkdir()

        monkeypatch.setattr(runtime, "init_user_db", lambda _path: None)

        _set_db_paths([str(base_path1), str(base_path2)], str(user_dir))

        # runtime state確認
        paths = runtime.get_base_database_paths()
        assert len(paths) == 2
        assert paths[0] == base_path1
        assert paths[1] == base_path2

    def test_set_db_paths_only_base_db(self, tmp_path: Path) -> None:
        """base_db_pathsのみ指定"""
        base_path = tmp_path / "base.db"
        base_path.touch()

        _set_db_paths([str(base_path)], None)

        paths = runtime.get_base_database_paths()
        assert len(paths) == 1
        assert paths[0] == base_path

    def test_set_db_paths_only_user_db(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """user_db_dirのみ指定"""
        user_dir = tmp_path / "user_db"
        user_dir.mkdir()

        self._mock_default_bases(monkeypatch, tmp_path)

        _set_db_paths(None, str(user_dir))

        # user_db初期化確認(runtime state check)
        # Note: runtime.user_db_pathはprivateなので、副作用の確認は制限される

    def test_set_db_paths_none_specified(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """両方未指定の場合（デフォルトDBを初期化）"""
        self._mock_default_bases(monkeypatch, tmp_path)
        # エラーなく完了すればOK
        _set_db_paths(None, None)


class TestMainParser:
    """Test CLI parser wiring."""

    @pytest.mark.parametrize(
        ("command_args", "handler_name"),
        [
            (["search", "--query", "cat"], "cmd_search"),
            (["stats"], "cmd_stats"),
            (["convert", "--tags", "cat", "--format-name", "danbooru"], "cmd_convert"),
            (
                [
                    "register",
                    "--tag",
                    "cat",
                    "--format-name",
                    "custom",
                    "--type-name",
                    "general",
                    "--user-db-dir",
                    "/tmp/user-db",
                ],
                "cmd_register",
            ),
        ],
    )
    def test_base_db_arg_is_available_to_commands(
        self,
        command_args: list[str],
        handler_name: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = MagicMock()
        monkeypatch.setattr(cli, handler_name, handler)
        monkeypatch.setattr(sys, "argv", ["tag-db", *command_args, "--base-db", "/tmp/base.sqlite"])

        main()

        handler.assert_called_once()
        args = handler.call_args.args[0]
        assert args.base_db == ["/tmp/base.sqlite"]

    def test_base_db_arg_accepts_multiple_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = MagicMock()
        monkeypatch.setattr(cli, "cmd_stats", handler)
        monkeypatch.setattr(
            sys,
            "argv",
            ["tag-db", "stats", "--base-db", "/tmp/base-a.sqlite", "--base-db", "/tmp/base-b.sqlite"],
        )

        main()

        handler.assert_called_once()
        args = handler.call_args.args[0]
        assert args.base_db == ["/tmp/base-a.sqlite", "/tmp/base-b.sqlite"]


class TestBuildRegisterService:
    """Test _build_register_service function."""

    def test_build_register_service_returns_service(self, qtbot) -> None:
        """TagRegisterServiceの正しいインスタンス生成

        Note: _build_register_service()はTagRepositoryを親として渡すが、
        TagRegisterServiceはQObject継承のためQObject親が必要。
        実際のCLI実行ではcmd_register内でのみ呼ばれ、Qt環境で動作する前提。
        """
        # FIXME: Issue #TBD参照 - CLI非Qt環境での動作検証が必要
        # 現状はQt環境前提の設計のため、Mockで代替
        from unittest.mock import MagicMock, patch

        from genai_tag_db_tools.cli import _build_register_service
        from genai_tag_db_tools.services.tag_register import TagRegisterService

        with patch("genai_tag_db_tools.cli.get_default_repository") as mock_repo:
            mock_repo.return_value = MagicMock()
            with patch("genai_tag_db_tools.cli.TagRegisterService") as mock_service_class:
                mock_service_instance = MagicMock(spec=TagRegisterService)
                mock_service_class.return_value = mock_service_instance

                service = _build_register_service()
                assert service == mock_service_instance
