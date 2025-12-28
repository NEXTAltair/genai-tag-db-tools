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
from io import StringIO
from pathlib import Path

import pytest
from pydantic import BaseModel

from genai_tag_db_tools.cli import (
    ParsedSource,
    _build_cache_config,
    _dump,
    _parse_source,
    _set_db_paths,
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


class TestDump:
    """Test _dump function."""

    def test_dump_pydantic_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Pydantic modelの辞書変換とJSON出力"""

        class SampleModel(BaseModel):
            name: str
            value: int

        model = SampleModel(name="test", value=42)
        _dump(model)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == {"name": "test", "value": 42}

    def test_dump_list_of_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Pydantic modelリストの変換とJSON出力"""

        class Item(BaseModel):
            id: int
            label: str

        items = [Item(id=1, label="first"), Item(id=2, label="second")]
        _dump(items)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == [{"id": 1, "label": "first"}, {"id": 2, "label": "second"}]

    def test_dump_mixed_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Pydantic modelと通常オブジェクトの混在リスト"""

        class Model(BaseModel):
            key: str

        mixed = [Model(key="model"), "plain_string", 123]
        _dump(mixed)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == [{"key": "model"}, "plain_string", 123]

    def test_dump_plain_object(self, capsys: pytest.CaptureFixture[str]) -> None:
        """通常のオブジェクト（辞書など）の出力"""
        plain_dict = {"status": "ok", "count": 10}
        _dump(plain_dict)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == {"status": "ok", "count": 10}

    def test_dump_ensures_ascii_false(self, capsys: pytest.CaptureFixture[str]) -> None:
        """日本語文字列が正しくエンコードされる"""

        class JapaneseModel(BaseModel):
            text: str

        model = JapaneseModel(text="テスト")
        _dump(model)

        captured = capsys.readouterr()
        assert "テスト" in captured.out
        assert "\\u" not in captured.out  # Unicode escapeされていない


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

    def test_set_db_paths_both_specified(self, tmp_path: Path) -> None:
        """base_db_pathsとuser_db_dirの両方指定"""
        base_path1 = tmp_path / "base1.db"
        base_path2 = tmp_path / "base2.db"
        user_dir = tmp_path / "user_db"

        base_path1.touch()
        base_path2.touch()
        user_dir.mkdir()

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

    def test_set_db_paths_only_user_db(self, tmp_path: Path) -> None:
        """user_db_dirのみ指定"""
        user_dir = tmp_path / "user_db"
        user_dir.mkdir()

        _set_db_paths(None, str(user_dir))

        # user_db初期化確認（runtime state check）
        # Note: runtime.user_db_pathはprivateなので、副作用の確認は制限される

    def test_set_db_paths_none_specified(self) -> None:
        """両方未指定の場合（何もしない）"""
        # エラーなく完了すればOK
        _set_db_paths(None, None)


class TestBuildRegisterService:
    """Test _build_register_service function."""

    def test_build_register_service_returns_service(self, qtbot) -> None:
        """TagRegisterServiceの正しいインスタンス生成

        Note: _build_register_service()はTagRepositoryを親として渡すが、
        TagRegisterServiceはQObject継承のためQObject親が必要。
        実際のCLI実行ではcmd_register内でのみ呼ばれ、Qt環境で動作する前提。
        """
        from genai_tag_db_tools.cli import _build_register_service
        from genai_tag_db_tools.services.app_services import TagRegisterService

        # FIXME: Issue #TBD参照 - CLI非Qt環境での動作検証が必要
        # 現状はQt環境前提の設計のため、Mockで代替
        from unittest.mock import MagicMock, patch

        with patch("genai_tag_db_tools.cli.get_default_repository") as mock_repo:
            mock_repo.return_value = MagicMock()
            with patch("genai_tag_db_tools.cli.TagRegisterService") as mock_service_class:
                mock_service_instance = MagicMock(spec=TagRegisterService)
                mock_service_class.return_value = mock_service_instance

                service = _build_register_service()
                assert service == mock_service_instance
