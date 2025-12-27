# genai_tag_db_tools/gui/converters.py
"""Data converters for GUI layer.

This module provides conversion utilities between Pydantic models (core_api layer)
and Polars DataFrames (GUI presentation layer).
"""

from __future__ import annotations

import polars as pl

from genai_tag_db_tools.models import TagSearchResult, TagStatisticsResult


def search_result_to_dataframe(
    result: TagSearchResult,
    *,
    show_usage_count: bool = True,
) -> pl.DataFrame:
    """Convert TagSearchResult to Polars DataFrame for GUI display.

    Args:
        result: Search result from core_api.search_tags()

    Returns:
        DataFrame with columns: tag, translations, format_statuses
    """
    if not result.items:
        return pl.DataFrame(
            schema={
                "tag": pl.Utf8,
                "translations": pl.Object,
                "format_statuses": pl.Object,
            }
        )

    rows = [
        {
            "tag": item.tag,
            "translations": item.translations or {},
            "format_statuses": item.format_statuses or {},
        }
        for item in result.items
    ]
    return pl.DataFrame(rows)


def statistics_result_to_dict(result: TagStatisticsResult) -> dict[str, int]:
    """Convert TagStatisticsResult to dictionary for GUI display.

    Args:
        result: Statistics result from core_api.get_statistics()

    Returns:
        Dictionary with keys: total_tags, total_aliases, total_formats, total_types
    """
    return {
        "total_tags": result.total_tags,
        "total_aliases": result.total_aliases,
        "total_formats": result.total_formats,
        "total_types": result.total_types,
    }
