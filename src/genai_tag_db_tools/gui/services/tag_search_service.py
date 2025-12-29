"""Tag search service for GUI."""

from typing import TYPE_CHECKING

import polars as pl
from PySide6.QtCore import QObject

from genai_tag_db_tools.db.repository import get_default_reader
from genai_tag_db_tools.gui.services.gui_service_base import GuiServiceBase
from genai_tag_db_tools.services.tag_search import TagSearcher
from genai_tag_db_tools.gui.services.tag_statistics_service import TagStatisticsService

if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader


class TagSearchService(GuiServiceBase):
    """GUI向け検索サービス(TagSearcher を利用)"""

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
            self._merged_reader = get_default_reader()
            self._merged_reader_initialized = True
        return self._merged_reader

    def get_tag_formats(self) -> list[str]:
        """タグフォーマット一覧を取得する"""
        try:
            return self._searcher.get_tag_formats()
        except Exception as e:
            self.logger.error("フォーマット一覧取得中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_tag_languages(self) -> list[str]:
        """言語一覧を取得する"""
        try:
            return self._searcher.get_tag_languages()
        except Exception as e:
            self.logger.error("言語一覧取得中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_tag_types(self, format_name: str | None) -> list[str]:
        """フォーマットに紐づくタグタイプ一覧を取得する"""
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
        """タグ検索を行い、Polars DataFrameで返す (core_api統合版)、検索結果をフィルタリングして返す
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
                "partial": partial,
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
