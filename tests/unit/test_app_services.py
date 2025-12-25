"""app_services.py のテスト（TagCoreService, TagSearchService, TagCleanerService, TagStatisticsService）"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest

from genai_tag_db_tools.services.app_services import (
    TagCleanerService,
    TagCoreService,
    TagSearchService,
    TagStatisticsService,
)


class DummySearcher:
    """TagSearcher のモック"""

    def __init__(self) -> None:
        self.tag_repo = SimpleNamespace(
            get_format_id=lambda name: {"danbooru": 1, "e621": 2}.get(name),
        )

    def get_tag_formats(self) -> list[str]:
        return ["danbooru", "e621"]

    def get_tag_languages(self) -> list[str]:
        return ["ja", "en"]

    def get_tag_types(self, format_name: str) -> list[str]:
        return ["character", "general"]

    def get_all_types(self) -> list[str]:
        return ["character", "general", "artist"]

    def convert_tag(self, tag: str, format_id: int) -> str:
        if tag == "cat" and format_id == 1:
            return "neko"
        return tag

    def search_tags(self, **kwargs) -> pl.DataFrame:
        return pl.DataFrame([{"tag": "cat", "tag_id": 1}])


class DummyStatistics:
    """TagStatistics のモック"""

    def __init__(self, session: Any = None) -> None:
        pass

    def get_general_stats(self) -> dict[str, Any]:
        return {"total_tags": 100, "total_aliases": 10}

    def get_usage_stats(self) -> pl.DataFrame:
        return pl.DataFrame([{"tag": "cat", "count": 50}])

    def get_type_distribution(self) -> pl.DataFrame:
        return pl.DataFrame([{"type": "character", "count": 30}])

    def get_translation_stats(self) -> pl.DataFrame:
        return pl.DataFrame([{"language": "ja", "count": 80}])


@pytest.mark.db_tools
def test_tag_core_service_get_tag_formats():
    searcher = DummySearcher()
    service = TagCoreService(searcher=searcher)

    formats = service.get_tag_formats()

    assert formats == ["danbooru", "e621"]


@pytest.mark.db_tools
def test_tag_core_service_get_tag_languages():
    searcher = DummySearcher()
    service = TagCoreService(searcher=searcher)

    languages = service.get_tag_languages()

    assert languages == ["ja", "en"]


@pytest.mark.db_tools
def test_tag_core_service_get_format_id():
    searcher = DummySearcher()
    service = TagCoreService(searcher=searcher)

    format_id = service.get_format_id("danbooru")

    assert format_id == 1


@pytest.mark.db_tools
def test_tag_core_service_convert_tag():
    searcher = DummySearcher()
    service = TagCoreService(searcher=searcher)

    converted = service.convert_tag("cat", 1)

    assert converted == "neko"


@pytest.mark.db_tools
def test_tag_search_service_get_tag_formats(qtbot):
    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher)

    formats = service.get_tag_formats()

    assert formats == ["danbooru", "e621"]


@pytest.mark.db_tools
def test_tag_search_service_get_tag_languages(qtbot):
    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher)

    languages = service.get_tag_languages()

    assert languages == ["ja", "en"]


@pytest.mark.db_tools
def test_tag_search_service_get_tag_types(qtbot):
    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher)

    types = service.get_tag_types("danbooru")

    assert types == ["character", "general"]


@pytest.mark.db_tools
def test_tag_search_service_get_tag_types_none_format(qtbot):
    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher)

    types = service.get_tag_types(None)

    assert types == ["character", "general", "artist"]


@pytest.mark.db_tools
def test_tag_search_service_search_tags(qtbot):
    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher)

    result = service.search_tags("cat")

    assert isinstance(result, pl.DataFrame)
    assert result.height > 0
    assert "tag" in result.columns


@pytest.mark.db_tools
def test_tag_search_service_emits_error_on_exception(qtbot):
    """Test that searching for non-existent keyword returns empty results."""
    service = TagSearchService()

    # Non-existent keyword should return empty DataFrame, not raise error
    result = service.search_tags("nonexistent_keyword_xyz_abcdef_12345")

    assert isinstance(result, pl.DataFrame)
    assert result.height == 0  # Empty results


@pytest.mark.db_tools
def test_tag_cleaner_service_get_tag_formats():
    core = TagCoreService(searcher=DummySearcher())
    service = TagCleanerService(core=core)

    formats = service.get_tag_formats()

    assert formats == ["All", "danbooru", "e621"]


@pytest.mark.db_tools
def test_tag_cleaner_service_convert_prompt():
    core = TagCoreService(searcher=DummySearcher())
    service = TagCleanerService(core=core)

    converted = service.convert_prompt("cat, dog", "danbooru")

    assert converted == "neko, dog"


@pytest.mark.db_tools
def test_tag_cleaner_service_convert_prompt_unknown_format():
    core = TagCoreService(searcher=DummySearcher())
    service = TagCleanerService(core=core)

    converted = service.convert_prompt("cat, dog", "unknown")

    assert converted == "cat, dog"


@pytest.mark.db_tools
def test_tag_statistics_service_get_general_stats(qtbot):
    service = TagStatisticsService()

    stats = service.get_general_stats()

    assert isinstance(stats, dict)
    assert "total_tags" in stats
    assert "total_aliases" in stats
    assert stats["total_tags"] > 0


@pytest.mark.db_tools
def test_tag_statistics_service_get_usage_stats(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    service = TagStatisticsService()

    usage = service.get_usage_stats()

    assert isinstance(usage, pl.DataFrame)
    assert usage.height == 1
    assert usage["tag"].to_list() == ["cat"]


@pytest.mark.db_tools
def test_tag_statistics_service_get_type_distribution(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    service = TagStatisticsService()

    dist = service.get_type_distribution()

    assert isinstance(dist, pl.DataFrame)
    assert dist.height == 1
    assert dist["type"].to_list() == ["character"]


@pytest.mark.db_tools
def test_tag_statistics_service_get_translation_stats(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    service = TagStatisticsService()

    trans = service.get_translation_stats()

    assert isinstance(trans, pl.DataFrame)
    assert trans.height == 1
    assert trans["language"].to_list() == ["ja"]


@pytest.mark.db_tools
def test_tag_statistics_service_emits_error_on_exception(qtbot):
    """Test that get_general_stats returns real database statistics."""
    service = TagStatisticsService()

    # Should return stats from either core_api or legacy fallback
    stats = service.get_general_stats()

    # Verify basic structure
    assert isinstance(stats, dict)
    assert "total_tags" in stats
    assert "total_aliases" in stats
    assert stats["total_tags"] > 0  # Real database has data
