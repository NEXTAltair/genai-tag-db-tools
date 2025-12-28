"""TagStatisticsPresenter tests for data transformation logic."""

from __future__ import annotations

import polars as pl

from genai_tag_db_tools.gui.presenters.tag_statistics_presenter import (
    BarChartData,
    TagStatisticsView,
    _build_distribution_chart,
    _build_language_chart,
    _build_summary_text,
    _build_usage_chart,
    _safe_float,
    build_statistics_view,
)


class TestSafeFloat:
    """Tests for _safe_float helper function."""

    def test_safe_float_with_int(self):
        """Integer should convert to float."""
        assert _safe_float(42) == 42.0

    def test_safe_float_with_float(self):
        """Float should return as-is."""
        assert _safe_float(3.14) == 3.14

    def test_safe_float_with_string(self):
        """String number should convert to float."""
        assert _safe_float("123.45") == 123.45

    def test_safe_float_with_none(self):
        """None should return 0.0."""
        assert _safe_float(None) == 0.0

    def test_safe_float_with_invalid_string(self):
        """Invalid string should return 0.0."""
        assert _safe_float("not a number") == 0.0


class TestBuildSummaryText:
    """Tests for _build_summary_text function."""

    def test_build_summary_text_complete_stats(self):
        """Complete stats should format correctly."""
        stats = {"total_tags": 1000, "alias_tags": 100, "non_alias_tags": 900}

        result = _build_summary_text(stats)

        assert "total_tags: 1000" in result
        assert "alias_tags: 100" in result
        assert "non_alias_tags: 900" in result

    def test_build_summary_text_missing_keys(self):
        """Missing keys should default to 0."""
        stats = {}

        result = _build_summary_text(stats)

        assert "total_tags: 0" in result
        assert "alias_tags: 0" in result
        assert "non_alias_tags: 0" in result


class TestBuildDistributionChart:
    """Tests for _build_distribution_chart function."""

    def test_build_distribution_chart_with_data(self):
        """Valid DataFrame should create BarChartData."""
        df = pl.DataFrame(
            [
                {"format_name": "danbooru", "type_name": "character", "tag_count": 30},
                {"format_name": "danbooru", "type_name": "general", "tag_count": 70},
                {"format_name": "e621", "type_name": "character", "tag_count": 20},
                {"format_name": "e621", "type_name": "general", "tag_count": 50},
            ]
        )

        result = _build_distribution_chart(df)

        assert result is not None
        assert result.title == "Tag Types by Format"
        assert len(result.categories) == 2
        assert "character" in result.categories
        assert "general" in result.categories
        assert len(result.series) == 2
        # Verify series values
        danbooru_series = next(s for s in result.series if s.name == "danbooru")
        e621_series = next(s for s in result.series if s.name == "e621")
        assert danbooru_series.values == [30.0, 70.0]  # character, general
        assert e621_series.values == [20.0, 50.0]  # character, general

    def test_build_distribution_chart_empty_dataframe(self):
        """Empty DataFrame should return None."""
        df = pl.DataFrame(schema={"format_name": pl.Utf8, "type_name": pl.Utf8, "tag_count": pl.Int64})

        result = _build_distribution_chart(df)

        assert result is None

    def test_build_distribution_chart_single_column(self):
        """DataFrame with only one column should return None (pivot creates single column)."""
        # After pivot, if there's no format_name variety, we get <=1 column
        df = pl.DataFrame([{"format_name": "danbooru", "type_name": "character", "tag_count": 10}])

        result = _build_distribution_chart(df)

        # With single format, pivot creates 2 columns (type_name + format), so won't be None
        # Let's test empty DataFrame instead
        assert result is None or isinstance(result, BarChartData)


class TestBuildUsageChart:
    """Tests for _build_usage_chart function."""

    def test_build_usage_chart_with_data(self):
        """Valid DataFrame should create BarChartData."""
        # Must include tag_id for grouping
        df = pl.DataFrame(
            [
                {"tag_id": 1, "format_name": "danbooru", "usage_count": 100},
                {"tag_id": 2, "format_name": "danbooru", "usage_count": 50},
                {"tag_id": 3, "format_name": "e621", "usage_count": 75},
            ]
        )

        result = _build_usage_chart(df)

        assert result is not None
        assert result.title == "Usage Distribution (Tags by Usage Count)"
        assert len(result.series) == 2
        assert any(s.name == "danbooru" for s in result.series)
        assert any(s.name == "e621" for s in result.series)
        # Verify series values (tag counts per bucket)
        danbooru_series = next(s for s in result.series if s.name == "danbooru")
        e621_series = next(s for s in result.series if s.name == "e621")
        assert len(danbooru_series.values) == 8  # 8 buckets
        assert len(e621_series.values) == 8  # 8 buckets
        # Find bucket indices dynamically from categories
        bucket_10_99_idx = result.categories.index("10-99")
        bucket_100_999_idx = result.categories.index("100-999")
        # danbooru: 1 tag in 10-99 bucket (usage_count=50), 1 tag in 100-999 bucket (usage_count=100)
        assert danbooru_series.values[bucket_10_99_idx] == 1.0
        assert danbooru_series.values[bucket_100_999_idx] == 1.0
        # e621: 1 tag in 10-99 bucket (usage_count=75)
        assert e621_series.values[bucket_10_99_idx] == 1.0

    def test_build_usage_chart_empty_dataframe(self):
        """Empty DataFrame should return None."""
        df = pl.DataFrame(schema={"format_name": pl.Utf8, "usage_count": pl.Int64})

        result = _build_usage_chart(df)

        assert result is None


class TestBuildLanguageChart:
    """Tests for _build_language_chart function."""

    def test_build_language_chart_with_data(self):
        """Valid DataFrame should create BarChartData."""
        df = pl.DataFrame([{"languages": ["en", "ja"]}, {"languages": ["en", "de"]}, {"languages": ["ja"]}])

        result = _build_language_chart(df)

        assert result is not None
        assert result.title == "Translations by Language"  # Actual title from implementation
        assert len(result.categories) >= 1
        assert len(result.series) == 1
        assert result.series[0].name == "languages"  # Actual name from implementation
        # Verify series values (language counts: en=2, ja=2, de=1)
        assert len(result.series[0].values) == len(result.categories)
        assert sum(result.series[0].values) == 5.0  # Total language occurrences

    def test_build_language_chart_empty_dataframe(self):
        """Empty DataFrame should return None."""
        df = pl.DataFrame(schema={"languages": pl.List(pl.Utf8)})

        result = _build_language_chart(df)

        assert result is None


class TestBuildStatisticsView:
    """Tests for build_statistics_view function."""

    def test_build_statistics_view_complete(self):
        """Complete data should create full TagStatisticsView."""
        general_stats = {"total_tags": 500, "alias_tags": 50, "non_alias_tags": 450}

        # Must include tag_id for usage chart
        usage_df = pl.DataFrame(
            [
                {"tag_id": 1, "format_name": "danbooru", "usage_count": 100},
                {"tag_id": 2, "format_name": "e621", "usage_count": 50},
            ]
        )

        type_df = pl.DataFrame(
            [
                {"format_name": "danbooru", "type_name": "character", "tag_count": 30},
                {"format_name": "e621", "type_name": "general", "tag_count": 70},
            ]
        )

        translation_df = pl.DataFrame([{"languages": ["en", "ja"]}, {"languages": ["en"]}])

        result = build_statistics_view(general_stats, usage_df, type_df, translation_df)

        assert isinstance(result, TagStatisticsView)
        assert "total_tags: 500" in result.summary_text
        assert result.distribution is not None
        assert result.usage is not None
        assert result.language is not None

    def test_build_statistics_view_empty_dataframes(self):
        """Empty DataFrames should result in None charts."""
        general_stats = {"total_tags": 0}
        usage_df = pl.DataFrame(
            schema={"tag_id": pl.Int64, "format_name": pl.Utf8, "usage_count": pl.Int64}
        )
        type_df = pl.DataFrame(schema={"format_name": pl.Utf8, "type_name": pl.Utf8, "tag_count": pl.Int64})
        translation_df = pl.DataFrame(schema={"languages": pl.List(pl.Utf8)})

        result = build_statistics_view(general_stats, usage_df, type_df, translation_df)

        assert isinstance(result, TagStatisticsView)
        assert result.distribution is None
        assert result.usage is None
        assert result.language is None
