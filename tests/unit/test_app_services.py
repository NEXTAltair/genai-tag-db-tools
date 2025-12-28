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
        self.reader = SimpleNamespace(
            get_format_id=lambda name: {"danbooru": 1, "e621": 2}.get(name),
            get_tag_formats=lambda: ["danbooru", "e621"],
            get_format_name=lambda format_id: {1: "danbooru", 2: "e621"}.get(format_id),
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

    def get_general_stats(self):
        from genai_tag_db_tools.models import GeneralStatsResult

        return GeneralStatsResult(
            total_tags=100, alias_tags=10, non_alias_tags=90, format_counts={"test": 50}
        )

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
def test_tag_core_service_convert_tag(monkeypatch):
    searcher = DummySearcher()
    service = TagCoreService(searcher=searcher)

    monkeypatch.setattr(
        "genai_tag_db_tools.services.app_services.get_default_reader",
        lambda: object(),
    )
    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.convert_tags",
        lambda _reader, tag, _format_name: "neko" if tag == "cat" else tag,
    )

    converted = service.convert_tag("cat", 1)

    assert converted == "neko"


@pytest.mark.db_tools
def test_tag_search_service_get_tag_formats(qtbot):
    from unittest.mock import Mock

    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher, merged_reader=Mock())

    formats = service.get_tag_formats()

    assert formats == ["danbooru", "e621"]


@pytest.mark.db_tools
def test_tag_search_service_get_tag_languages(qtbot):
    from unittest.mock import Mock

    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher, merged_reader=Mock())

    languages = service.get_tag_languages()

    assert languages == ["ja", "en"]


@pytest.mark.db_tools
def test_tag_search_service_get_tag_types(qtbot):
    from unittest.mock import Mock

    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher, merged_reader=Mock())

    types = service.get_tag_types("danbooru")

    assert types == ["character", "general"]


@pytest.mark.db_tools
def test_tag_search_service_get_tag_types_none_format(qtbot):
    from unittest.mock import Mock

    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher, merged_reader=Mock())

    types = service.get_tag_types(None)

    assert types == ["character", "general", "artist"]


@pytest.mark.db_tools
def test_tag_search_service_search_tags(qtbot, monkeypatch):
    from unittest.mock import Mock

    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher, merged_reader=Mock())

    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.search_tags",
        lambda *_args, **_kwargs: {"items": [{"tag": "cat", "tag_id": 1}], "total": 1},
    )
    monkeypatch.setattr(
        "genai_tag_db_tools.gui.converters.search_result_to_dataframe",
        lambda _result: pl.DataFrame([{"tag": "cat", "tag_id": 1}]),
    )

    result = service.search_tags("cat")

    assert isinstance(result, pl.DataFrame)
    assert result.height > 0
    assert "tag" in result.columns


@pytest.mark.db_tools
def test_tag_search_service_emits_error_on_exception(qtbot, monkeypatch):
    """Test that search_tags emits error signal and raises exception on failure."""
    from unittest.mock import Mock

    searcher = DummySearcher()
    service = TagSearchService(searcher=searcher, merged_reader=Mock())

    # Mock to raise an error
    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.search_tags",
        Mock(side_effect=RuntimeError("Test error"))
    )

    error_signals = []
    service.error_occurred.connect(lambda msg: error_signals.append(msg))

    # Should emit error signal and raise exception
    with pytest.raises(RuntimeError, match="Test error"):
        service.search_tags("test")

    assert len(error_signals) == 1
    assert "Test error" in error_signals[0]


@pytest.mark.db_tools
def test_tag_cleaner_service_get_tag_formats():
    core = TagCoreService(searcher=DummySearcher())
    service = TagCleanerService(core=core)

    formats = service.get_tag_formats()

    assert formats == ["danbooru", "e621"]


@pytest.mark.db_tools
def test_tag_cleaner_service_convert_prompt(monkeypatch):
    core = TagCoreService(searcher=DummySearcher())
    service = TagCleanerService(core=core)

    monkeypatch.setattr(
        "genai_tag_db_tools.services.app_services.get_default_reader",
        lambda: object(),
    )
    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.convert_tags",
        lambda _reader, tags, _format_name: tags.replace("cat", "neko"),
    )

    converted = service.convert_prompt("cat, dog", "danbooru")

    assert converted == "neko, dog"


@pytest.mark.db_tools
def test_tag_cleaner_service_convert_prompt_unknown_format(monkeypatch):
    core = TagCoreService(searcher=DummySearcher())
    service = TagCleanerService(core=core)

    monkeypatch.setattr(
        "genai_tag_db_tools.services.app_services.get_default_reader",
        lambda: object(),
    )
    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.convert_tags",
        lambda _reader, tags, _format_name: tags,
    )

    converted = service.convert_prompt("cat, dog", "unknown")

    assert converted == "cat, dog"


@pytest.mark.db_tools
def test_tag_statistics_service_get_general_stats(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    # Mock core_api to raise FileNotFoundError, forcing fallback to legacy
    def mock_get_statistics(_reader):
        raise FileNotFoundError("Mock DB not found")

    monkeypatch.setattr("genai_tag_db_tools.core_api.get_statistics", mock_get_statistics)
    # Inject mock merged_reader to avoid DB initialization
    service = TagStatisticsService(merged_reader=object())

    stats = service.get_general_stats()

    assert isinstance(stats, dict)
    assert "total_tags" in stats
    assert "alias_tags" in stats
    assert stats["total_tags"] > 0


@pytest.mark.db_tools
def test_tag_statistics_service_get_usage_stats(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    def mock_get_statistics(_reader):
        raise FileNotFoundError("Mock DB not found")

    monkeypatch.setattr("genai_tag_db_tools.core_api.get_statistics", mock_get_statistics)
    service = TagStatisticsService(merged_reader=object())

    usage = service.get_usage_stats()

    assert isinstance(usage, pl.DataFrame)
    assert usage.height == 1
    assert usage["tag"].to_list() == ["cat"]


@pytest.mark.db_tools
def test_tag_statistics_service_get_type_distribution(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    def mock_get_statistics(_reader):
        raise FileNotFoundError("Mock DB not found")

    monkeypatch.setattr("genai_tag_db_tools.core_api.get_statistics", mock_get_statistics)
    service = TagStatisticsService(merged_reader=object())

    dist = service.get_type_distribution()

    assert isinstance(dist, pl.DataFrame)
    assert dist.height == 1
    assert dist["type"].to_list() == ["character"]


@pytest.mark.db_tools
def test_tag_statistics_service_get_translation_stats(qtbot, monkeypatch):
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    def mock_get_statistics(_reader):
        raise FileNotFoundError("Mock DB not found")

    monkeypatch.setattr("genai_tag_db_tools.core_api.get_statistics", mock_get_statistics)
    service = TagStatisticsService(merged_reader=object())

    trans = service.get_translation_stats()

    assert isinstance(trans, pl.DataFrame)
    assert trans.height == 1
    assert trans["language"].to_list() == ["ja"]


@pytest.mark.db_tools
def test_tag_statistics_service_get_general_stats_fallback(qtbot, monkeypatch):
    """Test that get_general_stats falls back to legacy TagStatistics on core_api error."""
    monkeypatch.setattr("genai_tag_db_tools.services.app_services.TagStatistics", DummyStatistics)
    # Mock core_api to raise FileNotFoundError, forcing fallback to legacy
    def mock_get_statistics(_reader):
        raise FileNotFoundError("Mock DB not found")

    monkeypatch.setattr("genai_tag_db_tools.core_api.get_statistics", mock_get_statistics)
    # Inject mock merged_reader to avoid DB initialization
    service = TagStatisticsService(merged_reader=object())

    stats = service.get_general_stats()

    assert isinstance(stats, dict)
    assert "total_tags" in stats
    assert "alias_tags" in stats
    assert stats["total_tags"] > 0
