"""Integration tests for CLI commands.

HF Cache移行後の現在の実装に基づくテスト。
以下のコマンドをカバー:
- cmd_search: タグ検索
- cmd_register: タグ登録
- cmd_stats: 統計情報
- cmd_convert: タグ変換

Note: cmd_ensure_dbsはHF cache自動管理により実質的に不要になったため、
最小限のテストのみ実施。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from genai_tag_db_tools.cli import (
    cmd_convert,
    cmd_register,
    cmd_search,
    cmd_stats,
)
from genai_tag_db_tools.models import (
    TagRecordPublic,
    TagSearchResult,
    TagStatisticsResult,
)


class TestCmdSearch:
    """Test cmd_search command."""

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.cli.search_tags")
    def test_search_basic_query(
        self,
        mock_search: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """基本的なタグ検索クエリ実行"""
        # Mock response
        mock_result = TagSearchResult(
            items=[
                TagRecordPublic(
                    tag="test_tag",
                    source_tag=None,
                    tag_id=1,
                    format_name="danbooru",
                    type_id=1,
                    type_name="general",
                    alias=False,
                    deprecated=False,
                    usage_count=100,
                    translations=None,
                    format_statuses=None,
                )
            ],
            total=1,
        )
        mock_search.return_value = mock_result

        # Execute command
        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            query="test",
            format_name=None,
            type_name=None,
            resolve_preferred=False,
            include_aliases=False,
            include_deprecated=False,
            exact=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_search(args)

        # Verify search_tags called with correct request
        assert mock_search.called
        request = mock_search.call_args[0][1]
        assert request.query == "test"

        # Verify output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["total"] == 1
        assert len(output["items"]) == 1
        assert output["items"][0]["tag"] == "test_tag"

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.cli.search_tags")
    def test_search_with_filters(
        self, mock_search: MagicMock, mock_reader: MagicMock, tmp_path: Path
    ) -> None:
        """フィルタ付きタグ検索"""
        mock_search.return_value = TagSearchResult(items=[], total=0)

        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            query="character",
            format_name=["danbooru"],
            type_name=["character"],
            resolve_preferred=True,
            include_aliases=True,
            include_deprecated=False,
            exact=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_search(args)

        # Verify request parameters
        request = mock_search.call_args[0][1]
        assert request.query == "character"
        assert request.format_names == ["danbooru"]
        assert request.type_names == ["character"]
        assert request.resolve_preferred is True
        assert request.include_aliases is True
        assert request.include_deprecated is False


class TestCmdRegister:
    """Test cmd_register command."""

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

    @patch("genai_tag_db_tools.cli._build_register_service")
    @patch("genai_tag_db_tools.cli.register_tag")
    def test_register_basic_tag(
        self,
        mock_register: MagicMock,
        mock_service: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """基本的なタグ登録"""
        self._mock_default_bases(monkeypatch, tmp_path)
        # Mock response
        mock_result = TagRecordPublic(
            tag="new_tag",
            source_tag=None,
            tag_id=2,
            format_name="custom",
            type_id=1,
            type_name="general",
            alias=False,
            deprecated=False,
            usage_count=0,
            translations=None,
            format_statuses=None,
        )
        mock_register.return_value = mock_result

        # Execute command
        user_db = tmp_path / "user_db"
        user_db.mkdir()
        args = argparse.Namespace(
            tag="new_tag",
            source_tag=None,
            format_name="custom",
            type_name="general",
            alias=False,
            preferred_tag=None,
            translation=[],
            base_db=None,
            user_db_dir=str(user_db),
        )
        cmd_register(args)

        # Verify register_tag called
        assert mock_register.called
        request = mock_register.call_args[0][1]
        assert request.tag == "new_tag"
        assert request.format_name == "custom"
        assert request.type_name == "general"

        # Verify output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["tag"] == "new_tag"

    def test_register_without_user_db_raises_error(self) -> None:
        """user_db_dir未指定でエラー"""
        args = argparse.Namespace(
            tag="tag",
            format_name="custom",
            type_name="general",
            alias=False,
            preferred_tag=None,
            translation=[],
            base_db=None,
            user_db_dir=None,
        )

        with pytest.raises(ValueError, match="--user-db-dir is required"):
            cmd_register(args)

    @patch("genai_tag_db_tools.cli._build_register_service")
    @patch("genai_tag_db_tools.cli.register_tag")
    def test_register_with_translations(
        self,
        mock_register: MagicMock,
        mock_service: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """翻訳付きタグ登録"""
        self._mock_default_bases(monkeypatch, tmp_path)
        mock_result = TagRecordPublic(
            tag="translated_tag",
            source_tag=None,
            tag_id=3,
            format_name="custom",
            type_id=1,
            type_name="general",
            alias=False,
            deprecated=False,
            usage_count=0,
            translations={"ja": ["翻訳タグ"], "en": ["Translated Tag"]},
            format_statuses=None,
        )
        mock_register.return_value = mock_result

        user_db = tmp_path / "user_db"
        user_db.mkdir()
        args = argparse.Namespace(
            tag="translated_tag",
            source_tag=None,
            format_name="custom",
            type_name="general",
            alias=False,
            preferred_tag=None,
            translation=[("ja", "翻訳タグ"), ("en", "Translated Tag")],
            base_db=None,
            user_db_dir=str(user_db),
        )
        cmd_register(args)

        # Verify translations passed correctly
        request = mock_register.call_args[0][1]
        assert request.translations is not None
        assert len(request.translations) == 2
        assert request.translations[0].language == "ja"
        assert request.translations[0].translation == "翻訳タグ"


class TestCmdStats:
    """Test cmd_stats command."""

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.cli.get_statistics")
    def test_stats_command(
        self,
        mock_stats: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """統計情報取得コマンド実行"""
        # Mock response
        mock_result = TagStatisticsResult(
            total_tags=1000, total_aliases=200, total_formats=5, total_types=10
        )
        mock_stats.return_value = mock_result

        # Execute command
        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(base_db=[str(base_db)], user_db_dir=None)
        cmd_stats(args)

        # Verify get_statistics called
        assert mock_stats.called

        # Verify output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["total_tags"] == 1000
        assert output["total_aliases"] == 200
        assert output["total_formats"] == 5
        assert output["total_types"] == 10


class TestCmdConvert:
    """Test cmd_convert command."""

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.convert_tags")
    def test_convert_basic(
        self,
        mock_convert: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """基本的なタグ変換（テキスト出力）"""
        mock_convert.return_value = "tag1, tag2, tag3"

        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            tags="tag1,tag2,tag3",
            format_name="danbooru",
            separator=", ",
            json=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_convert(args)

        # Verify convert_tags called
        assert mock_convert.called
        assert mock_convert.call_args[0][1] == "tag1,tag2,tag3"
        assert mock_convert.call_args[0][2] == "danbooru"

        # Verify text output
        captured = capsys.readouterr()
        assert captured.out.strip() == "tag1, tag2, tag3"

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.convert_tags")
    def test_convert_json_output(
        self,
        mock_convert: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """タグ変換（JSON出力）"""
        mock_convert.return_value = "converted1, converted2"

        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            tags="original1,original2",
            format_name="e621",
            separator=", ",
            json=True,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_convert(args)

        # Verify JSON output structure
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["input"] == "original1,original2"
        assert output["output"] == "converted1, converted2"
        assert output["format"] == "e621"

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.convert_tags")
    def test_convert_custom_separator(
        self, mock_convert: MagicMock, mock_reader: MagicMock, tmp_path: Path
    ) -> None:
        """カスタムセパレータでのタグ変換"""
        mock_convert.return_value = "tag1|tag2|tag3"

        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            tags="tag1,tag2,tag3",
            format_name="custom",
            separator="|",
            json=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_convert(args)

        # Verify separator parameter
        assert mock_convert.call_args[1]["separator"] == "|"
