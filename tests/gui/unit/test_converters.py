"""Converters utility tests."""

from __future__ import annotations

import polars as pl
import pytest

from genai_tag_db_tools.gui.converters import search_result_to_dataframe, statistics_result_to_dict
from genai_tag_db_tools.models import TagRecordPublic, TagSearchResult, TagStatisticsResult


class TestSearchResultToDataFrame:
    """Tests for search_result_to_dataframe function."""

    def test_empty_result_returns_empty_dataframe_with_schema(self):
        """Empty result should return DataFrame with correct schema."""
        result = TagSearchResult(items=[], total=0)

        df = search_result_to_dataframe(result)

        assert isinstance(df, pl.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == ["tag", "translations", "format_statuses"]

    def test_single_item_conversion(self):
        """Single search result item should convert correctly."""
        tag_record = TagRecordPublic(
            tag="cat",
            translations={"ja": ["猫"], "en": ["cat"]},
            format_statuses={"danbooru": {"type": "general", "usage_count": 100}},
        )
        result = TagSearchResult(items=[tag_record], total=1)

        df = search_result_to_dataframe(result)

        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["tag"] == "cat"
        assert row["translations"] == {"ja": ["猫"], "en": ["cat"]}
        assert row["format_statuses"] == {"danbooru": {"type": "general", "usage_count": 100}}

    def test_multiple_items_conversion(self):
        """Multiple search result items should convert correctly."""
        items = [
            TagRecordPublic(
                tag="cat",
                translations={"ja": ["猫"]},
                format_statuses={"danbooru": {"type": "general"}},
            ),
            TagRecordPublic(
                tag="dog",
                translations={"ja": ["犬"]},
                format_statuses={"e621": {"type": "species"}},
            ),
        ]
        result = TagSearchResult(items=items, total=2)

        df = search_result_to_dataframe(result)

        assert len(df) == 2
        assert df["tag"].to_list() == ["cat", "dog"]

    def test_none_values_converted_to_empty_dict(self):
        """None translations and format_statuses should convert to empty dict."""
        tag_record = TagRecordPublic(tag="test", translations=None, format_statuses=None)
        result = TagSearchResult(items=[tag_record], total=1)

        df = search_result_to_dataframe(result)

        row = df.row(0, named=True)
        assert row["translations"] == {}
        assert row["format_statuses"] == {}


class TestStatisticsResultToDict:
    """Tests for statistics_result_to_dict function."""

    def test_statistics_conversion(self):
        """Statistics result should convert to dictionary correctly."""
        result = TagStatisticsResult(
            total_tags=1000, total_aliases=200, total_formats=5, total_types=10
        )

        stats_dict = statistics_result_to_dict(result)

        assert stats_dict == {
            "total_tags": 1000,
            "total_aliases": 200,
            "total_formats": 5,
            "total_types": 10,
        }

    def test_statistics_with_zero_values(self):
        """Statistics with zero values should convert correctly."""
        result = TagStatisticsResult(total_tags=0, total_aliases=0, total_formats=0, total_types=0)

        stats_dict = statistics_result_to_dict(result)

        assert stats_dict == {
            "total_tags": 0,
            "total_aliases": 0,
            "total_formats": 0,
            "total_types": 0,
        }
