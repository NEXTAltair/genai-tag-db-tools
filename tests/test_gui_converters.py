# tests/test_gui_converters.py
"""Unit tests for GUI data converters."""

import polars as pl

from genai_tag_db_tools.gui.converters import (
    search_result_to_dataframe,
    statistics_result_to_dict,
)
from genai_tag_db_tools.models import (
    TagRecordPublic,
    TagSearchResult,
    TagStatisticsResult,
)


class TestSearchResultToDataFrame:
    """Tests for search_result_to_dataframe conversion."""

    def test_empty_result(self):
        """Empty search result should return empty DataFrame with correct schema."""
        result = TagSearchResult(items=[], total=0)
        df = search_result_to_dataframe(result)

        assert isinstance(df, pl.DataFrame)
        assert df.is_empty()
        assert set(df.columns) == {"tag", "source_tag", "format_name", "type_name", "alias", "usage_count"}

    def test_single_item(self):
        """Single item should be converted correctly."""
        items = [
            TagRecordPublic(
                tag="girl",
                source_tag="1girl",
                format_name="danbooru",
                type_name="general",
                alias=False,
            )
        ]
        result = TagSearchResult(items=items, total=1)
        df = search_result_to_dataframe(result)

        assert len(df) == 1
        assert df["tag"][0] == "girl"
        assert df["source_tag"][0] == "1girl"
        assert df["format_name"][0] == "danbooru"
        assert df["type_name"][0] == "general"
        assert df["alias"][0] is False

    def test_multiple_items(self):
        """Multiple items should be converted correctly."""
        items = [
            TagRecordPublic(
                tag="girl",
                source_tag="1girl",
                format_name="danbooru",
                type_name="general",
                alias=False,
            ),
            TagRecordPublic(
                tag="boy",
                source_tag="1boy",
                format_name="danbooru",
                type_name="general",
                alias=False,
            ),
        ]
        result = TagSearchResult(items=items, total=2)
        df = search_result_to_dataframe(result)

        assert len(df) == 2
        assert df["tag"].to_list() == ["girl", "boy"]
        assert df["source_tag"].to_list() == ["1girl", "1boy"]

    def test_null_values(self):
        """Null values in optional fields should be handled correctly."""
        items = [
            TagRecordPublic(
                tag="unknown",
                source_tag=None,
                format_name=None,
                type_name=None,
                alias=None,
            )
        ]
        result = TagSearchResult(items=items, total=1)
        df = search_result_to_dataframe(result)

        assert len(df) == 1
        assert df["tag"][0] == "unknown"
        assert df["source_tag"][0] is None
        assert df["format_name"][0] is None
        assert df["type_name"][0] is None
        assert df["alias"][0] is None


class TestStatisticsResultToDict:
    """Tests for statistics_result_to_dict conversion."""

    def test_basic_conversion(self):
        """Statistics result should be converted to dictionary correctly."""
        result = TagStatisticsResult(total_tags=1000, total_aliases=50, total_formats=5, total_types=10)
        stats_dict = statistics_result_to_dict(result)

        assert stats_dict == {
            "total_tags": 1000,
            "total_aliases": 50,
            "total_formats": 5,
            "total_types": 10,
        }

    def test_zero_values(self):
        """Zero values should be preserved."""
        result = TagStatisticsResult(total_tags=0, total_aliases=0, total_formats=0, total_types=0)
        stats_dict = statistics_result_to_dict(result)

        assert all(value == 0 for value in stats_dict.values())
