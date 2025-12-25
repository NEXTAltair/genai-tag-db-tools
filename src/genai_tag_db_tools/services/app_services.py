# genai_tag_db_tools/services/app_services.py

import logging
from typing import TYPE_CHECKING, Any

import polars as pl
from PySide6.QtCore import QObject, Signal
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.services.tag_search import TagSearcher
from genai_tag_db_tools.services.tag_statistics import TagStatistics

if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult


class GuiServiceBase(QObject):
    """GUI向けの共通基底クラス（シグナル/ロガー）。"""

    progress_updated = Signal(int, str)  # (progress, message)
    process_finished = Signal(str)  # (message)
    error_occurred = Signal(str)  # (error message)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

    def close(self) -> None:
        """リソース解放（サブクラスでオーバーライド可能）。"""
        self.logger.info("Closing %s", self.__class__.__name__)
        # Signal の切断
        try:
            self.disconnect()
        except TypeError:
            # No connections to disconnect
            pass


class TagCoreService:
    """DBのコア検索/変換機能をまとめた軽量サービス。"""

    def __init__(self, searcher: TagSearcher | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._searcher = searcher or TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """タグフォーマット一覧を取得する。"""
        return self._searcher.get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        """言語一覧を取得する。"""
        return self._searcher.get_tag_languages()

    def get_format_id(self, format_name: str) -> int:
        """フォーマット名からIDを取得する。"""
        return self._searcher.tag_repo.get_format_id(format_name)

    def convert_tag(self, tag: str, format_id: int) -> str:
        """単一タグを指定フォーマットに変換する。"""
        return self._searcher.convert_tag(tag, format_id)


class TagSearchService(GuiServiceBase):
    """GUI向け検索サービス（TagSearcher を利用）。"""

    def __init__(
        self,
        parent: QObject | None = None,
        searcher: TagSearcher | None = None,
        merged_reader: "MergedTagReader | None" = None,
    ):
        super().__init__(parent)
        self._searcher = searcher or TagSearcher()
        # Store merged_reader, will be lazy-initialized on first use if None
        self._merged_reader = merged_reader
        self._merged_reader_initialized = merged_reader is not None

    def _get_merged_reader(self) -> "MergedTagReader":
        """Lazy-initialize MergedTagReader if not provided."""
        if not self._merged_reader_initialized:
            from genai_tag_db_tools.db.repository import MergedTagReader, get_default_repository

            repo = get_default_repository()
            if isinstance(repo, MergedTagReader):
                self._merged_reader = repo
            else:
                self._merged_reader = MergedTagReader(base_repo=repo, user_repo=None)
            self._merged_reader_initialized = True
        return self._merged_reader

    def get_tag_formats(self) -> list[str]:
        """タグフォーマット一覧を取得する。"""
        try:
            return self._searcher.get_tag_formats()
        except Exception as e:
            self.logger.error("フォーマット一覧取得中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_tag_languages(self) -> list[str]:
        """言語一覧を取得する。"""
        try:
            return self._searcher.get_tag_languages()
        except Exception as e:
            self.logger.error("言語一覧取得中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_tag_types(self, format_name: str | None) -> list[str]:
        """フォーマットに紐づくタグタイプ一覧を取得する。"""
        try:
            if format_name is None:
                return self._searcher.get_all_types()
            return self._searcher.get_tag_types(format_name)
        except Exception as e:
            self.logger.error("タグタイプ一覧取得中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def search_tags(
        self,
        keyword: str,
        partial: bool = False,
        format_name: str | None = None,
        type_name: str | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
    ) -> pl.DataFrame:
        """タグ検索を行い、Polars DataFrameで返す (core_api統合版)。

        Args:
            keyword: Search keyword.
            partial: Whether to use partial matching.
            format_name: Optional format filter.
            type_name: Optional type filter.
            language: Optional language filter (not yet supported by core_api).
            min_usage: Optional minimum usage filter.
            max_usage: Optional maximum usage filter.
            alias: Whether to include aliases.
        Returns:
            検索結果の Polars DataFrame
        """
        try:
            from genai_tag_db_tools import core_api
            from genai_tag_db_tools.gui.converters import search_result_to_dataframe
            from genai_tag_db_tools.models import TagSearchRequest

            # Build TagSearchRequest with proper format/type filtering
            format_names = [format_name] if format_name else None
            type_names = [type_name] if type_name else None

            request_kwargs = {
                "query": keyword,
                "format_names": format_names,
                "type_names": type_names,
                "resolve_preferred": True,
                "include_aliases": alias if alias is not None else True,
                "include_deprecated": False,
                "min_usage": min_usage,
                "max_usage": max_usage,
            }

            request = TagSearchRequest(**request_kwargs)

            # Call core_api with MergedTagReader (lazy init if needed)
            result = core_api.search_tags(self._get_merged_reader(), request)

            # Convert to DataFrame for GUI display
            df = search_result_to_dataframe(result)

            # Apply additional filters (language, usage) not supported by core_api yet
            if language:
                # TODO: Implement language filtering when core_api supports it
                self.logger.warning("Language filtering not yet supported in core_api integration")

            return df

        except Exception as e:
            self.logger.error("タグ検索中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise


class TagCleanerService(GuiServiceBase):
    """GUIの一括変換など簡易処理をまとめるサービス。"""

    def __init__(self, parent: QObject | None = None, core: TagCoreService | None = None):
        super().__init__(parent)
        self._core = core or TagCoreService()

    def get_tag_formats(self) -> list[str]:
        """フォーマット一覧に 'All' を付けて返す。"""
        format_list = ["All"]
        format_list.extend(self._core.get_tag_formats())
        return format_list

    def convert_prompt(self, prompt: str, format_name: str) -> str:
        """カンマ区切りのタグを指定フォーマットへ変換する。"""
        self.logger.info("TagCleanerService: convert_prompt() called")

        format_id = self._core.get_format_id(format_name)
        if format_id is None:
            self.logger.warning("Unknown format: %s", format_name)
            return prompt

        raw_tags = [t.strip() for t in prompt.split(",")]
        converted_list = [self._core.convert_tag(tag, format_id) for tag in raw_tags]
        return ", ".join(converted_list)


class TagImportService(GuiServiceBase):
    """Legacy import flow placeholder (removed in refactor)."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        raise NotImplementedError("Tag import flow was removed; use HF base DB instead.")


class TagRegisterService(GuiServiceBase):
    """GUI向けのタグ登録サービス。"""

    def __init__(self, parent: QObject | None = None, repository: TagRepository | None = None):
        super().__init__(parent)
        self._repo = repository if repository else TagRepository()

    def register_tag(self, request: "TagRegisterRequest") -> "TagRegisterResult":
        """Register a tag and optional metadata via the repository.

        Args:
            request: Tag registration request.
        Returns:
            TagRegisterResult indicating whether the tag was created.
        """
        from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult

        if not isinstance(request, TagRegisterRequest):
            msg = "TagRegisterRequest 以外の入力は受け付けません。"
            self.logger.error(msg)
            raise TypeError(msg)

        try:
            tag = request.tag
            source_tag = request.source_tag or request.tag
            fmt_id = self._repo.get_format_id(request.format_name)
            if fmt_id is None:
                raise ValueError(f"format_name が無効です: {request.format_name}")

            type_id = self._repo.get_type_id(request.type_name)
            if type_id is None:
                raise ValueError(f"type_name が無効です: {request.type_name}")

            existing_id = self._repo.get_tag_id_by_name(tag, partial=False)
            tag_id = self._repo.create_tag(source_tag, tag)
            created = existing_id is None

            preferred_tag_id = tag_id
            if request.alias:
                if not request.preferred_tag:
                    raise ValueError("alias=True の場合は preferred_tag が必要です。")
                preferred_tag_id = self._repo.get_tag_id_by_name(request.preferred_tag, partial=False)
                if preferred_tag_id is None:
                    raise ValueError(f"推奨タグが見つかりません: {request.preferred_tag}")

            if request.translations:
                for tr in request.translations:
                    self._repo.add_or_update_translation(tag_id, tr.language, tr.translation)

            self._repo.update_tag_status(
                tag_id=tag_id,
                format_id=fmt_id,
                alias=request.alias,
                preferred_tag_id=preferred_tag_id,
                type_id=type_id,
            )

            return TagRegisterResult(created=created)

        except Exception as e:
            self.logger.error("タグ登録中にエラー発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def register_or_update_tag(self, tag_info: dict) -> int:
        """タグ登録/更新を行う。"""
        try:
            normalized_tag = tag_info.get("normalized_tag")
            source_tag = tag_info.get("source_tag")
            format_name = tag_info.get("format_name", "")
            type_name = tag_info.get("type_name", "")
            usage_count = tag_info.get("use_count", 0)
            language = tag_info.get("language", "")
            translation = tag_info.get("translation", "")

            if not normalized_tag or not source_tag:
                raise ValueError("タグまたはソースタグが空です。")

            if format_name and type_name:
                from genai_tag_db_tools.models import TagRegisterRequest, TagTranslationInput

                translations = None
                if language and translation:
                    translations = [TagTranslationInput(language=language, translation=translation)]

                self.register_tag(
                    TagRegisterRequest(
                        tag=normalized_tag,
                        source_tag=source_tag,
                        format_name=format_name,
                        type_name=type_name,
                        translations=translations,
                    )
                )
                tag_id = self._repo.get_tag_id_by_name(normalized_tag, partial=False)
                if tag_id is None:
                    raise ValueError("登録後にタグIDが見つかりません。")
                if usage_count > 0:
                    fmt_id = self._repo.get_format_id(format_name)
                    self._repo.update_usage_count(tag_id, fmt_id, usage_count)
                return tag_id

            fmt_id = self._repo.get_format_id(format_name)
            type_id = self._repo.get_type_id(type_name) if type_name else None

            tag_id = self._repo.create_tag(source_tag, normalized_tag)

            if usage_count > 0:
                self._repo.update_usage_count(tag_id, fmt_id, usage_count)

            if language and translation:
                self._repo.add_or_update_translation(tag_id, language, translation)

            self._repo.update_tag_status(
                tag_id=tag_id,
                format_id=fmt_id,
                alias=False,
                preferred_tag_id=tag_id,
                type_id=type_id,
            )

            return tag_id

        except Exception as e:
            self.logger.error("タグ登録中にエラー発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_tag_details(self, tag_id: int) -> pl.DataFrame:
        """登録後のタグ詳細を取得する。"""
        try:
            tag_obj = self._repo.get_tag_by_id(tag_id)
            if not tag_obj:
                return pl.DataFrame()

            status_list = self._repo.list_tag_statuses(tag_id)
            translations = self._repo.get_translations(tag_id)

            rows = [
                {
                    "tag": tag_obj.tag,
                    "source_tag": tag_obj.source_tag,
                    "formats": [s.format_id for s in status_list],
                    "types": [s.type_id for s in status_list],
                    "total_usage_count": sum(
                        self._repo.get_usage_count(tag_id, s.format_id) or 0 for s in status_list
                    ),
                    "translations": {t.language: t.translation for t in translations},
                }
            ]

            return pl.DataFrame(rows)

        except Exception as e:
            self.logger.error("タグ詳細取得中にエラー発生: %s", e)
            self.error_occurred.emit(str(e))
            raise


class TagStatisticsService(GuiServiceBase):
    """統計取得用のGUIサービス。"""

    def __init__(
        self,
        parent: QObject | None = None,
        session: Session | None = None,
        merged_reader: "MergedTagReader | None" = None,
    ):
        super().__init__(parent)
        self._stats = TagStatistics(session=session)
        # Store merged_reader, will be lazy-initialized on first use if None
        self._merged_reader = merged_reader
        self._merged_reader_initialized = merged_reader is not None

    def _get_merged_reader(self) -> "MergedTagReader":
        """Lazy-initialize MergedTagReader if not provided."""
        if not self._merged_reader_initialized:
            from genai_tag_db_tools.db.repository import MergedTagReader, get_default_repository

            base_repo = get_default_repository()
            self._merged_reader = MergedTagReader(base_repo=base_repo, user_repo=None)
            self._merged_reader_initialized = True
        return self._merged_reader

    def get_general_stats(self) -> dict[str, Any]:
        """全体サマリを取得する (core_api統合版)。"""
        try:
            # First try core_api integration
            try:
                from genai_tag_db_tools import core_api
                from genai_tag_db_tools.gui.converters import statistics_result_to_dict

                # Use core_api.get_statistics() with MergedTagReader
                result = core_api.get_statistics(self._get_merged_reader())
                return statistics_result_to_dict(result)
            except FileNotFoundError as e:
                # Fall back to legacy TagStatistics if core_api fails
                self.logger.warning("core_api statistics failed, falling back to legacy: %s", e)
                return self._stats.get_general_stats()

        except Exception as e:
            self.logger.error("統計取得中にエラーが発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_usage_stats(self) -> pl.DataFrame:
        """使用回数統計を取得する。"""
        try:
            return self._stats.get_usage_stats()
        except Exception as e:
            self.logger.error("使用回数統計取得中にエラーが発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_type_distribution(self) -> pl.DataFrame:
        """タイプ分布統計を取得する。"""
        try:
            return self._stats.get_type_distribution()
        except Exception as e:
            self.logger.error("タイプ分布統計取得中にエラーが発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_translation_stats(self) -> pl.DataFrame:
        """翻訳統計を取得する。"""
        try:
            return self._stats.get_translation_stats()
        except Exception as e:
            self.logger.error("翻訳統計取得中にエラーが発生: %s", e)
            self.error_occurred.emit(str(e))
            raise
