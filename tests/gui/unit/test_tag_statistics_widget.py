"""TagStatisticsWidget のテスト（pytest-qt ベース）"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest

from genai_tag_db_tools.gui.widgets.tag_statistics import TagStatisticsWidget
from genai_tag_db_tools.services.app_services import TagStatisticsService


class MockTagStatisticsService(TagStatisticsService):
    """TagStatisticsService のモック"""

    def __init__(self):
        self.mock_get_general_stats = MagicMock(
            return_value={"total_tags": 100, "alias_tags": 10, "non_alias_tags": 90}
        )
        self.mock_get_usage_stats = MagicMock(
            return_value=pl.DataFrame(
                [
                    {"tag_id": 1, "format_name": "danbooru", "usage_count": 50},
                    {"tag_id": 2, "format_name": "danbooru", "usage_count": 20},
                ]
            )
        )
        self.mock_get_type_distribution = MagicMock(
            return_value=pl.DataFrame(
                [
                    {"format_name": "danbooru", "type_name": "character", "tag_count": 30},
                    {"format_name": "danbooru", "type_name": "general", "tag_count": 70},
                ]
            )
        )
        self.mock_get_translation_stats = MagicMock(
            return_value=pl.DataFrame(
                [
                    {"tag_id": 1, "total_translations": 1, "languages": ["ja"]},
                    {"tag_id": 2, "total_translations": 2, "languages": ["en", "ja"]},
                ]
            )
        )

    def get_general_stats(self) -> dict[str, Any]:
        return self.mock_get_general_stats()

    def get_usage_stats(self) -> pl.DataFrame:
        return self.mock_get_usage_stats()

    def get_type_distribution(self) -> pl.DataFrame:
        return self.mock_get_type_distribution()

    def get_translation_stats(self) -> pl.DataFrame:
        return self.mock_get_translation_stats()


@pytest.fixture
def tag_statistics_widget(qtbot):
    """TagStatisticsWidget fixture with mock service"""
    service = MockTagStatisticsService()
    widget = TagStatisticsWidget(parent=None, service=service)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.db_tools
def test_tag_statistics_widget_initialization(qtbot):
    """Widget が正しく初期化される"""
    service = MockTagStatisticsService()
    widget = TagStatisticsWidget(parent=None, service=service)
    qtbot.addWidget(widget)

    assert widget.service is service
    assert widget._initialized is False
    assert widget.view_state is None


@pytest.mark.db_tools
def test_tag_statistics_widget_set_service(qtbot, tag_statistics_widget):
    """set_service() でサービスを設定できる"""
    new_service = MockTagStatisticsService()
    tag_statistics_widget.set_service(new_service)

    assert tag_statistics_widget.service is new_service
    assert tag_statistics_widget._initialized is False


@pytest.mark.db_tools
def test_tag_statistics_widget_showEvent_does_not_auto_initialize(qtbot, tag_statistics_widget):
    """showEvent() では自動初期化しない（Generate ボタンクリック必須）"""
    tag_statistics_widget.show()
    qtbot.waitExposed(tag_statistics_widget)

    # Statistics widget doesn't auto-initialize on show
    assert tag_statistics_widget.view_state is None


@pytest.mark.db_tools
def test_tag_statistics_widget_generate_button_initializes(qtbot, tag_statistics_widget):
    """Generate ボタンクリックで統計が生成される"""
    tag_statistics_widget.on_statsGenerateButton_clicked()

    assert tag_statistics_widget.view_state is not None
    tag_statistics_widget.service.mock_get_general_stats.assert_called_once()


@pytest.mark.db_tools
def test_tag_statistics_widget_initialize_fetches_data(qtbot, tag_statistics_widget):
    """initialize() でデータを取得する"""
    tag_statistics_widget.initialize()

    tag_statistics_widget.service.mock_get_general_stats.assert_called_once()
    tag_statistics_widget.service.mock_get_usage_stats.assert_called_once()
    tag_statistics_widget.service.mock_get_type_distribution.assert_called_once()
    tag_statistics_widget.service.mock_get_translation_stats.assert_called_once()


@pytest.mark.db_tools
def test_tag_statistics_widget_update_summary(qtbot, tag_statistics_widget):
    """update_summary() でサマリーテキストを更新する"""
    tag_statistics_widget.initialize()

    # Summary label should have text
    assert tag_statistics_widget.labelSummary.text() != ""


@pytest.mark.db_tools
def test_tag_statistics_widget_update_distribution_chart(qtbot, tag_statistics_widget):
    """update_distribution_chart() で分布チャートを作成する"""
    tag_statistics_widget.initialize()

    # Chart layout should have widget
    assert tag_statistics_widget.chartLayoutDistribution.count() > 0


@pytest.mark.db_tools
def test_tag_statistics_widget_update_usage_chart(qtbot, tag_statistics_widget):
    """update_usage_chart() で使用統計チャートを作成する"""
    tag_statistics_widget.initialize()

    # Chart layout should have widget
    assert tag_statistics_widget.chartLayoutUsage.count() > 0


@pytest.mark.db_tools
def test_tag_statistics_widget_update_language_chart(qtbot, tag_statistics_widget):
    """update_language_chart() で言語チャートを作成する"""
    tag_statistics_widget.initialize()

    # Chart layout should have widget
    assert tag_statistics_widget.chartLayoutLanguage.count() > 0


@pytest.mark.db_tools
def test_tag_statistics_widget_update_top_tags(qtbot, tag_statistics_widget):
    """update_top_tags() でトップタグリストを更新する"""
    tag_statistics_widget.initialize()

    # Top tags list should have items
    assert tag_statistics_widget.listWidgetTopTags.count() > 0
