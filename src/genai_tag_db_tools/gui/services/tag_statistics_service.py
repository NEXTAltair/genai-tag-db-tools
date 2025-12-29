"""Tag statistics service for GUI."""

from typing import TYPE_CHECKING, Any

import polars as pl
from PySide6.QtCore import QObject
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import get_default_reader
from genai_tag_db_tools.gui.services.gui_service_base import GuiServiceBase
from genai_tag_db_tools.services.tag_statistics import TagStatistics

if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader


class TagStatisticsService(GuiServiceBase):
    """統計取得用のGUIサービス"""

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
        self._cache_version: str | None = None
        self._cache_general_stats: dict[str, Any] | None = None
        self._cache_usage_df: pl.DataFrame | None = None
        self._cache_type_dist_df: pl.DataFrame | None = None
        self._cache_translation_df: pl.DataFrame | None = None

    def _get_cache_version(self) -> str | None:
        try:
            reader = getattr(self._stats, "reader", None)
            if reader is not None and hasattr(reader, "get_database_version"):
                return reader.get_database_version()
        except Exception as e:
            self.logger.warning("Failed to read database version for cache: %s", e)
        return None

    def _compute_general_stats(self) -> dict[str, Any]:
        try:
            from genai_tag_db_tools import core_api
            from genai_tag_db_tools.gui.converters import statistics_result_to_dict

            result = core_api.get_statistics(self._get_merged_reader())
            stats: dict[str, Any] = statistics_result_to_dict(result)
        except FileNotFoundError as e:
            self.logger.warning("core_api statistics failed, falling back to legacy: %s", e)
            stats = self._stats.get_general_stats().model_dump()

        if "format_counts" not in stats:
            try:
                stats["format_counts"] = self._stats.get_format_counts()
            except Exception as e:
                self.logger.warning("Failed to compute format_counts: %s", e)
                stats["format_counts"] = {}

        return stats

    def _refresh_cache(self, version: str | None) -> None:
        self._cache_version = version
        self._cache_general_stats = self._compute_general_stats()
        self._cache_usage_df = self._stats.get_usage_stats()
        self._cache_type_dist_df = self._stats.get_type_distribution()
        self._cache_translation_df = self._stats.get_translation_stats()

    def _ensure_cache(self) -> None:
        version = self._get_cache_version()
        if self._cache_general_stats is None:
            self._refresh_cache(version)
            return
        if version is None and self._cache_version is None:
            return
        if version != self._cache_version:
            self._refresh_cache(version)

    def _get_merged_reader(self) -> "MergedTagReader":
        """Lazy-initialize MergedTagReader if not provided."""
        if not self._merged_reader_initialized:
            self._merged_reader = get_default_reader()
            self._merged_reader_initialized = True
        return self._merged_reader

    def get_general_stats(self) -> dict[str, Any]:
        """全体サマリを取得する(core_api統合版)"""
        try:
            self._ensure_cache()
            return self._cache_general_stats or {}

        except Exception as e:
            self.logger.error("統計取得中にエラーが発生しました: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_usage_stats(self) -> pl.DataFrame:
        """使用回数統計を取得する"""
        try:
            self._ensure_cache()
            return self._cache_usage_df if self._cache_usage_df is not None else pl.DataFrame([])
        except Exception as e:
            self.logger.error("使用回数統計取得中にエラーが発生しました: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_type_distribution(self) -> pl.DataFrame:
        """タイプ別集計を取得する"""
        try:
            self._ensure_cache()
            return self._cache_type_dist_df if self._cache_type_dist_df is not None else pl.DataFrame([])
        except Exception as e:
            self.logger.error("タイプ別集計取得中にエラーが発生しました: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_translation_stats(self) -> pl.DataFrame:
        """翻訳統計を取得する"""
        try:
            self._ensure_cache()
            return (
                self._cache_translation_df if self._cache_translation_df is not None else pl.DataFrame([])
            )
        except Exception as e:
            self.logger.error("翻訳統計取得中にエラーが発生しました: %s", e)
            self.error_occurred.emit(str(e))
            raise
