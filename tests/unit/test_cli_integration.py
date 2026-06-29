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
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from genai_tag_db_tools.cli import (
    cmd_convert,
    cmd_recommend_record,
    cmd_recommend_tag,
    cmd_recommend_translation,
    cmd_register,
    cmd_search,
    cmd_stats,
)
from genai_tag_db_tools.models import (
    RefinementReason,
    RefinementRecommendation,
    RefinementSuggestion,
    TagRecordPublic,
    TagRegisterResult,
    TagSearchResult,
    TagStatisticsResult,
)


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL stdout into a list of JSON objects (1 line = 1 object)."""
    return [json.loads(line) for line in output.splitlines() if line.strip()]


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
            limit=50,
            offset=0,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_search(args)

        # Verify search_tags called with correct request
        assert mock_search.called
        request = mock_search.call_args[0][1]
        assert request.query == "test"
        assert request.limit == 50
        assert request.offset == 0

        # Verify JSONL output: 1 item line + final result line
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["ok"] is True
        assert lines[-1]["count"] == 1
        assert lines[-1]["total"] == 1
        items = [line for line in lines if line["kind"] == "item"]
        assert len(items) == 1
        assert items[0]["tag"] == "test_tag"

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
            limit=50,
            offset=0,
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

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.cli.search_tags")
    def test_search_limit_zero_means_unlimited(
        self, mock_search: MagicMock, mock_reader: MagicMock, tmp_path: Path
    ) -> None:
        """--limit 0 は無制限 (request.limit=None) の opt-in"""
        mock_search.return_value = TagSearchResult(items=[], total=0)

        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            query="cat",
            format_name=None,
            type_name=None,
            resolve_preferred=False,
            include_aliases=False,
            include_deprecated=False,
            exact=False,
            limit=0,
            offset=0,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_search(args)

        request = mock_search.call_args[0][1]
        assert request.limit is None


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
        mock_register.return_value = TagRegisterResult(created=True, tag_id=2)

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

        # Verify JSONL result line
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["created"] is True
        assert lines[-1]["tag_id"] == 2

    @patch("genai_tag_db_tools.cli._build_register_service")
    @patch("genai_tag_db_tools.cli.register_tag")
    def test_register_without_user_db_falls_back_to_default(
        self,
        mock_register: MagicMock,
        mock_service: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """#25 案A: user_db_dir 未指定でも default_cache_dir() へフォールバックして登録できる"""
        self._mock_default_bases(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "genai_tag_db_tools.io.hf_downloader.default_cache_dir",
            lambda: tmp_path / "default_cache",
        )
        mock_register.return_value = TagRegisterResult(created=True, tag_id=7)

        args = argparse.Namespace(
            tag="tag",
            source_tag=None,
            format_name="custom",
            type_name="general",
            alias=False,
            preferred_tag=None,
            translation=[],
            base_db=None,
            user_db_dir=None,
        )
        cmd_register(args)

        # フォールバックでも register_tag が呼ばれ、result 行が出る
        assert mock_register.called
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["created"] is True
        assert lines[-1]["tag_id"] == 7

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
        mock_register.return_value = TagRegisterResult(created=True, tag_id=3)

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

        # Verify JSONL result line
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["total_tags"] == 1000
        assert lines[-1]["total_aliases"] == 200
        assert lines[-1]["total_formats"] == 5
        assert lines[-1]["total_types"] == 10


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
        """基本的なタグ変換 (JSONL 出力に統一)"""
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

        # Verify JSONL result line (no more plain-text branch)
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["input"] == "tag1,tag2,tag3"
        assert lines[-1]["output"] == "tag1, tag2, tag3"
        assert lines[-1]["format"] == "danbooru"

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.convert_tags")
    def test_convert_json_flag_is_deprecated_noop(
        self,
        mock_convert: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json は後方互換で受理されるが出力は常に JSONL (deprecated no-op)"""
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

        # --json 有無に関わらず同じ JSONL result 行になる
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["input"] == "original1,original2"
        assert lines[-1]["output"] == "converted1, converted2"
        assert lines[-1]["format"] == "e621"

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


class TestCmdRecommendTag:
    """Test cmd_recommend_tag command (thin adapter, batch, read-only)."""

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.recommend_manual_refinement")
    def test_batch_emits_item_per_tag_plus_result(
        self,
        mock_recommend: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """複数タグで kind=item×N + kind=result(件数サマリ)を出す。"""

        def _fake(tag: str, repo: object, *, format_name: str) -> RefinementRecommendation:
            needs = tag == "flower"
            return RefinementRecommendation(
                source_tag=tag,
                normalized_tag=tag,
                needs_refinement=needs,
                score=1.0 if needs else 0.0,
                reasons=[RefinementReason(code="broad_single_word", message="x")] if needs else [],
                suggestions=[RefinementSuggestion(kind="review_only")] if needs else [],
            )

        mock_recommend.side_effect = _fake

        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            tag=["flower,1girl"],
            file=None,
            format_name="danbooru",
            rule_only=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_recommend_tag(args)

        # core_api へ委譲。format_name と repo が配線される。
        assert mock_recommend.call_count == 2
        assert mock_recommend.call_args_list[0].kwargs["format_name"] == "danbooru"
        assert mock_recommend.call_args_list[0].args[1] is mock_reader.return_value

        lines = _parse_jsonl(capsys.readouterr().out)
        items = [line for line in lines if line["kind"] == "item"]
        assert [item["source_tag"] for item in items] == ["flower", "1girl"]
        assert lines[-1]["kind"] == "result"
        assert lines[-1]["total"] == 2
        assert lines[-1]["needs_refinement_count"] == 1

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.recommend_manual_refinement")
    def test_single_tag_still_emits_item_and_result(
        self,
        mock_recommend: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """単一タグでも出力形状は item + result で一定。"""
        mock_recommend.return_value = RefinementRecommendation(
            source_tag="flower",
            normalized_tag="flower",
            needs_refinement=False,
            score=0.0,
        )
        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            tag=["flower"],
            file=None,
            format_name="unknown",
            rule_only=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_recommend_tag(args)

        lines = _parse_jsonl(capsys.readouterr().out)
        assert [line["kind"] for line in lines] == ["item", "result"]
        assert lines[-1]["total"] == 1
        assert lines[-1]["needs_refinement_count"] == 0

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.recommend_manual_refinement")
    def test_reads_tags_from_file(
        self,
        mock_recommend: MagicMock,
        mock_reader: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--file は1行1タグで読み、空行を捨てる。"""
        mock_recommend.side_effect = lambda tag, repo, *, format_name: RefinementRecommendation(
            source_tag=tag, normalized_tag=tag, needs_refinement=False, score=0.0
        )
        tags_file = tmp_path / "tags.txt"
        tags_file.write_text("flower\n\n1girl\n", encoding="utf-8")
        base_db = tmp_path / "base.db"
        base_db.touch()
        args = argparse.Namespace(
            tag=None,
            file=str(tags_file),
            format_name="unknown",
            rule_only=False,
            base_db=[str(base_db)],
            user_db_dir=None,
        )
        cmd_recommend_tag(args)

        lines = _parse_jsonl(capsys.readouterr().out)
        items = [line for line in lines if line["kind"] == "item"]
        assert [item["source_tag"] for item in items] == ["flower", "1girl"]

    def test_no_tags_emits_error_and_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """タグ未指定(stdin も tty)なら構造化エラー + exit 2。"""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        args = argparse.Namespace(
            tag=None,
            file=None,
            format_name="unknown",
            rule_only=False,
            base_db=None,
            user_db_dir=None,
        )
        with pytest.raises(SystemExit) as exc:
            cmd_recommend_tag(args)
        assert exc.value.code == 2
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[-1]["kind"] == "error"
        assert lines[-1]["code"] == "INVALID_INPUT"

    @patch("genai_tag_db_tools.cli.get_default_reader")
    @patch("genai_tag_db_tools.core_api.recommend_manual_refinement")
    def test_rule_only_bypasses_db_reader(
        self,
        mock_recommend: MagicMock,
        mock_reader: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--rule-only は DB 初期化/readers を使わず repo=None 経路へ委譲する。"""
        mock_recommend.return_value = RefinementRecommendation(
            source_tag="flower",
            normalized_tag="flower",
            needs_refinement=True,
            score=0.6,
            reasons=[RefinementReason(code="broad_single_word", message="broad")],
            suggestions=[RefinementSuggestion(kind="review_only")],
        )
        args = argparse.Namespace(
            tag=["flower"],
            file=None,
            format_name="unknown",
            rule_only=True,
            base_db=None,
            user_db_dir=None,
        )

        cmd_recommend_tag(args)

        mock_reader.assert_not_called()
        mock_recommend.assert_called_once()
        assert mock_recommend.call_args.args[1] is None
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[0]["reasons"][0]["code"] == "broad_single_word"


class TestCmdRecommendTranslation:
    """Test cmd_recommend_translation command (rule-only, no DB)."""

    @patch("genai_tag_db_tools.core_api.recommend_translation_quality")
    def test_delegates_and_emits_result(
        self,
        mock_recommend: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """core_api へ委譲し、recommendation を result 行に展開する。"""
        mock_recommend.return_value = RefinementRecommendation(
            source_tag="flower",
            normalized_tag="flower",
            needs_refinement=True,
            score=1.0,
            reasons=[RefinementReason(code="missing_translation", message="empty")],
            suggestions=[RefinementSuggestion(kind="review_only")],
        )
        args = argparse.Namespace(
            source_tag="flower",
            translation="",
            language="ja",
            target_scope=None,
            target_tag_id=None,
        )
        cmd_recommend_translation(args)

        mock_recommend.assert_called_once_with(
            "flower",
            "",
            language="ja",
            target_scope=None,
            target_tag_id=None,
        )
        lines = _parse_jsonl(capsys.readouterr().out)
        assert len(lines) == 1
        assert lines[0]["kind"] == "result"
        assert lines[0]["source_tag"] == "flower"
        assert lines[0]["needs_refinement"] is True
        assert lines[0]["reasons"][0]["code"] == "missing_translation"

    @patch("genai_tag_db_tools.core_api.recommend_translation_quality")
    def test_target_args_are_forwarded_for_proposals(
        self,
        mock_recommend: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """target scope/id を core_api へ渡し、proposal 付き recommendation を出力する。"""
        mock_recommend.return_value = RefinementRecommendation(
            source_tag="flower",
            normalized_tag="flower",
            needs_refinement=True,
            score=0.9,
            reasons=[RefinementReason(code="wrong_language_translation", message="wrong")],
            suggestions=[RefinementSuggestion(kind="review_only")],
        )
        args = argparse.Namespace(
            source_tag="flower",
            translation="flower",
            language="ja",
            target_scope="user",
            target_tag_id=1_000_000_001,
        )

        cmd_recommend_translation(args)

        mock_recommend.assert_called_once_with(
            "flower",
            "flower",
            language="ja",
            target_scope="user",
            target_tag_id=1_000_000_001,
        )
        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines[0]["kind"] == "result"


class TestCmdRecommendRecord:
    """Test cmd_recommend_record command (search JSONL stdin adapter)."""

    @patch("genai_tag_db_tools.core_api.recommend_tag_record_refinement")
    def test_reads_search_items_from_stdin(
        self,
        mock_recommend: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_recommend.side_effect = lambda row, **_kwargs: RefinementRecommendation(
            source_tag=row["tag"],
            normalized_tag=row["tag"],
            needs_refinement=row["tag"] == "flower",
            score=0.6 if row["tag"] == "flower" else 0.0,
            reasons=[RefinementReason(code="broad_single_word", message="broad")]
            if row["tag"] == "flower"
            else [],
            suggestions=[RefinementSuggestion(kind="review_only")] if row["tag"] == "flower" else [],
        )
        stdin = io.StringIO(
            "\n".join(
                [
                    json.dumps({"kind": "item", "tag": "flower", "tag_id": 1, "format_name": "danbooru"}),
                    json.dumps({"kind": "result", "ok": True, "message": "search completed"}),
                    json.dumps({"kind": "item", "tag": "1girl", "tag_id": 2, "format_name": "danbooru"}),
                ]
            )
        )
        monkeypatch.setattr("sys.stdin", stdin)
        args = argparse.Namespace(
            format_name="danbooru",
            target_scope="base",
            base_db=None,
            user_db_dir=None,
        )

        cmd_recommend_record(args)

        assert mock_recommend.call_count == 2
        assert mock_recommend.call_args_list[0].kwargs == {
            "format_name": "danbooru",
            "target_scope": "base",
            "repo": None,
        }
        lines = _parse_jsonl(capsys.readouterr().out)
        assert [line["kind"] for line in lines] == ["item", "item", "result"]
        assert lines[-1]["total"] == 2
        assert lines[-1]["needs_refinement_count"] == 1

    def test_upstream_error_line_is_invalid_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stdin = io.StringIO(
            json.dumps(
                {
                    "kind": "error",
                    "ok": False,
                    "code": "DB_ERROR",
                    "message": "upstream failed",
                }
            )
        )
        monkeypatch.setattr("sys.stdin", stdin)
        args = argparse.Namespace(format_name=None, target_scope=None, base_db=None, user_db_dir=None)

        with pytest.raises(ValueError, match="upstream error"):
            cmd_recommend_record(args)

    def test_empty_search_result_stream_is_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        stdin = io.StringIO(json.dumps({"kind": "result", "ok": True, "message": "search completed"}))
        monkeypatch.setattr("sys.stdin", stdin)
        args = argparse.Namespace(format_name=None, target_scope=None, base_db=None, user_db_dir=None)

        cmd_recommend_record(args)

        lines = _parse_jsonl(capsys.readouterr().out)
        assert lines == [
            {
                "kind": "result",
                "ok": True,
                "message": "record recommendations completed",
                "total": 0,
                "needs_refinement_count": 0,
            }
        ]

    def test_malformed_item_missing_tag_id_is_invalid_input(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stdin = io.StringIO(json.dumps({"kind": "item", "tag": "flower"}))
        monkeypatch.setattr("sys.stdin", stdin)
        args = argparse.Namespace(format_name=None, target_scope=None, base_db=None, user_db_dir=None)

        with pytest.raises(ValueError, match="missing tag_id"):
            cmd_recommend_record(args)

    @patch("genai_tag_db_tools.core_api.recommend_tag_record_refinement")
    def test_numeric_format_status_keys_fall_back_to_row_level_without_repo(
        self,
        mock_recommend: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_recommend.return_value = RefinementRecommendation(
            source_tag="custom tag",
            normalized_tag="custom tag",
            needs_refinement=False,
            score=0.0,
        )
        stdin = io.StringIO(
            json.dumps(
                {
                    "kind": "item",
                    "tag": "custom tag",
                    "tag_id": 1_000_000_001,
                    "format_name": "Lorairo",
                    "format_statuses": {
                        "1000": {
                            "alias": False,
                            "deprecated": False,
                            "type_id": 0,
                            "type_name": "unknown",
                            "preferred_tag_id": 1_000_000_001,
                        }
                    },
                }
            )
        )
        monkeypatch.setattr("sys.stdin", stdin)
        args = argparse.Namespace(format_name=None, target_scope=None, base_db=None, user_db_dir=None)

        cmd_recommend_record(args)

        passed_row = mock_recommend.call_args.args[0]
        assert "format_statuses" not in passed_row
        assert mock_recommend.call_args.kwargs["repo"] is None

    @patch("genai_tag_db_tools.core_api.recommend_tag_record_refinement")
    def test_mixed_format_status_keys_are_preserved_without_repo(
        self,
        mock_recommend: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_recommend.return_value = RefinementRecommendation(
            source_tag="custom tag",
            normalized_tag="custom tag",
            needs_refinement=True,
            score=0.5,
        )
        format_statuses = {
            "e621": {
                "alias": False,
                "deprecated": False,
                "type_id": 0,
                "type_name": "general",
                "preferred_tag_id": 1_000_000_001,
            },
            "1000": {
                "alias": False,
                "deprecated": False,
                "type_id": 0,
                "type_name": "unknown",
                "preferred_tag_id": 1_000_000_001,
            },
        }
        stdin = io.StringIO(
            json.dumps(
                {
                    "kind": "item",
                    "tag": "custom tag",
                    "tag_id": 1_000_000_001,
                    "format_name": "Lorairo",
                    "format_statuses": format_statuses,
                }
            )
        )
        monkeypatch.setattr("sys.stdin", stdin)
        args = argparse.Namespace(format_name="danbooru", target_scope=None, base_db=None, user_db_dir=None)

        cmd_recommend_record(args)

        passed_row = mock_recommend.call_args.args[0]
        assert passed_row["format_statuses"] == format_statuses
        assert mock_recommend.call_args.kwargs["repo"] is None
