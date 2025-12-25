# tests/unit/test_app_services_core_api_integration.py
"""Unit tests for app_services core_api integration."""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from pydantic import ValidationError

from genai_tag_db_tools.models import TagRecordPublic, TagSearchResult, TagStatisticsResult
from genai_tag_db_tools.services.app_services import TagSearchService, TagStatisticsService


class TestTagSearchServiceCoreApiIntegration:
    """Tests for TagSearchService core_api integration."""

    def test_search_tags_with_language_filter_logs_warning(self, qtbot):
        """Language filter should log warning when not supported by core_api."""
        mock_searcher = MagicMock()
        service = TagSearchService(searcher=mock_searcher)

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
            patch.object(service.logger, "warning") as mock_warning,
        ):
            # Setup mock返却値
            mock_core_api.search_tags.return_value = TagSearchResult(items=[], total=0)

            # language付きで検索
            result = service.search_tags(keyword="test", language="ja")

            # WARNING ログが出力されることを確認
            mock_warning.assert_called_once()
            assert "Language filtering not yet supported" in mock_warning.call_args[0][0]
            assert isinstance(result, pl.DataFrame)

    def test_search_tags_with_usage_filter_passed(self, qtbot):
        """Usage count filter should be passed to core_api."""
        mock_searcher = MagicMock()
        service = TagSearchService(searcher=mock_searcher)

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
        ):
            # Setup mock???
            mock_core_api.search_tags.return_value = TagSearchResult(items=[], total=0)

            # usage filter?????
            result = service.search_tags(keyword="test", min_usage=10, max_usage=100)

            call_args = mock_core_api.search_tags.call_args
            request = call_args[0][1]
            assert request.min_usage == 10
            assert request.max_usage == 100
            assert isinstance(result, pl.DataFrame)

    def test_search_tags_with_core_api_success(self, qtbot):
        """Successful core_api search should return DataFrame."""
        mock_searcher = MagicMock()
        service = TagSearchService(searcher=mock_searcher)

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
        ):
            # Setup mock返却値
            mock_items = [
                TagRecordPublic(
                    tag="girl",
                    source_tag="1girl",
                    format_name="danbooru",
                    type_name="general",
                    alias=False,
                )
            ]
            mock_core_api.search_tags.return_value = TagSearchResult(items=mock_items, total=1)

            # 検索実行
            result = service.search_tags(keyword="girl", format_name="danbooru", type_name="general")

            # DataFrame が返されることを確認
            assert isinstance(result, pl.DataFrame)
            assert len(result) == 1
            assert result["tag"][0] == "girl"

    def test_search_tags_validation_error_raises(self, qtbot):
        """ValidationError should propagate."""
        service = TagSearchService(searcher=MagicMock())

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
        ):
            # core_api ?EValidationError ??????
            # Create a real ValidationError by validating invalid data
            from genai_tag_db_tools.models import TagSearchRequest

            try:
                TagSearchRequest(query=None)  # Invalid: query is required
            except ValidationError as ve:
                validation_error = ve

            mock_core_api.search_tags.side_effect = validation_error

            with pytest.raises(ValidationError):
                service.search_tags(keyword="test")

    def test_search_tags_file_not_found_raises(self, qtbot):
        """FileNotFoundError should propagate."""
        service = TagSearchService(searcher=MagicMock())

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
        ):
            # core_api ?EFileNotFoundError ??????
            mock_core_api.search_tags.side_effect = FileNotFoundError("DB file not found")

            with pytest.raises(FileNotFoundError):
                service.search_tags(keyword="test")


class TestTagStatisticsServiceCoreApiIntegration:
    """Tests for TagStatisticsService core_api integration."""

    def test_get_general_stats_with_core_api_success(self, qtbot):
        """Successful core_api statistics should return dict."""
        mock_session = MagicMock()

        with patch("genai_tag_db_tools.services.app_services.TagStatistics") as mock_stats_class:
            mock_stats = MagicMock()
            mock_stats_class.return_value = mock_stats

            service = TagStatisticsService(session=mock_session)

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
        ):
            # Setup mock返却値
            mock_result = TagStatisticsResult(
                total_tags=1000, total_aliases=50, total_formats=5, total_types=10
            )
            mock_core_api.get_statistics.return_value = mock_result

            # 統計取得
            result = service.get_general_stats()

            # dict が返されることを確認
            assert isinstance(result, dict)
            assert result["total_tags"] == 1000
            assert result["total_aliases"] == 50
            assert result["total_formats"] == 5
            assert result["total_types"] == 10

    def test_get_general_stats_file_not_found_fallback(self, qtbot):
        """FileNotFoundError should trigger fallback to legacy statistics."""
        mock_session = MagicMock()

        with patch("genai_tag_db_tools.services.app_services.TagStatistics") as mock_stats_class:
            mock_stats = MagicMock()
            mock_stats.get_general_stats.return_value = {
                "total_tags": 100,
                "total_aliases": 10,
                "total_formats": 2,
                "total_types": 5,
            }
            mock_stats_class.return_value = mock_stats

            service = TagStatisticsService(session=mock_session)

        with (
            patch.object(service, "_get_merged_reader"),
            patch("genai_tag_db_tools.core_api") as mock_core_api,
            patch.object(service.logger, "warning") as mock_warning,
        ):
            # core_api が FileNotFoundError を発生させる
            mock_core_api.get_statistics.side_effect = FileNotFoundError("DB file not found")

            # 統計取得
            result = service.get_general_stats()

            # fallback が呼ばれることを確認
            mock_stats.get_general_stats.assert_called_once()
            mock_warning.assert_called()
            assert "core_api statistics failed, falling back to legacy" in mock_warning.call_args[0][0]
            assert isinstance(result, dict)
            assert result["total_tags"] == 100
