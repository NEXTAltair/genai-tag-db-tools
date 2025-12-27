from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class BarSeriesData:
    name: str
    values: list[float]


@dataclass(frozen=True)
class BarChartData:
    title: str
    categories: list[str]
    series: list[BarSeriesData]


@dataclass(frozen=True)
class TagStatisticsView:
    summary_text: str
    distribution: BarChartData | None
    usage: BarChartData | None
    language: BarChartData | None


def _safe_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _build_summary_text(general_stats: dict) -> str:
    total_tags = general_stats.get("total_tags", 0)
    alias_tags = general_stats.get("alias_tags", 0)
    non_alias_tags = general_stats.get("non_alias_tags", 0)
    format_counts = general_stats.get("format_counts") or {}

    lines = [
        f"total_tags: {total_tags}",
        f"alias_tags: {alias_tags}",
        f"non_alias_tags: {non_alias_tags}",
    ]
    if format_counts:
        lines.append("format_counts:")
        for format_name in sorted(format_counts.keys()):
            lines.append(f"  {format_name}: {format_counts[format_name]}")
    return "\n".join(lines) + "\n"


def _build_distribution_chart(type_df: pl.DataFrame) -> BarChartData | None:
    if type_df.is_empty():
        return None

    pivoted = type_df.pivot(
        on="format_name", index="type_name", values="tag_count", aggregate_function="first"
    ).fill_null(0)

    columns = pivoted.columns
    if len(columns) <= 1:
        return None

    category_col = columns[0]
    format_cols = columns[1:]
    categories = pivoted.select(pl.col(category_col)).to_series().to_list()

    series: list[BarSeriesData] = []
    for fmt_name in format_cols:
        values: list[float] = []
        for row in pivoted.iter_rows(named=True):
            values.append(_safe_float(row.get(fmt_name)))
        series.append(BarSeriesData(name=fmt_name, values=values))

    return BarChartData(
        title="Tag Types by Format",
        categories=[str(item) for item in categories],
        series=series,
    )


def _build_usage_chart(usage_df: pl.DataFrame) -> BarChartData | None:
    if usage_df.is_empty():
        return None

    bucket = (
        pl.when(pl.col("usage_count") <= 0)
        .then("0")
        .when(pl.col("usage_count") < 10)
        .then("1-9")
        .when(pl.col("usage_count") < 100)
        .then("10-99")
        .when(pl.col("usage_count") < 1_000)
        .then("100-999")
        .when(pl.col("usage_count") < 10_000)
        .then("1k-9k")
        .when(pl.col("usage_count") < 100_000)
        .then("10k-99k")
        .when(pl.col("usage_count") < 1_000_000)
        .then("100k-999k")
        .otherwise("1M+")
        .alias("usage_bucket")
    )

    bucket_order = ["0", "1-9", "10-99", "100-999", "1k-9k", "10k-99k", "100k-999k", "1M+"]

    bucketed = usage_df.with_columns(bucket)
    grouped = (
        bucketed.group_by(["format_name", "usage_bucket"])
        .agg([pl.len().alias("tag_count")])
        .sort(["format_name", "usage_bucket"])
    )

    formats = sorted(bucketed["format_name"].unique().to_list())
    series: list[BarSeriesData] = []
    for fmt_name in formats:
        values: list[float] = []
        fmt_rows = grouped.filter(pl.col("format_name") == fmt_name)
        fmt_map = {
            row["usage_bucket"]: _safe_float(row["tag_count"]) for row in fmt_rows.iter_rows(named=True)
        }
        for bucket_name in bucket_order:
            values.append(fmt_map.get(bucket_name, 0.0))
        series.append(BarSeriesData(name=fmt_name, values=values))

    return BarChartData(
        title="Usage Distribution (Tags by Usage Count)",
        categories=bucket_order,
        series=series,
    )


def _build_language_chart(translation_df: pl.DataFrame) -> BarChartData | None:
    if translation_df.is_empty():
        return None

    exploded = translation_df.explode("languages")
    freq = exploded.group_by("languages").agg([pl.len().alias("count")])
    freq = freq.sort("count", descending=True)
    if freq.is_empty():
        return None

    categories: list[str] = []
    values: list[float] = []
    for row in freq.iter_rows(named=True):
        categories.append(str(row["languages"]))
        values.append(_safe_float(row["count"]))

    return BarChartData(
        title="Translations by Language",
        categories=categories,
        series=[BarSeriesData(name="languages", values=values)],
    )


def build_statistics_view(
    general_stats: dict,
    usage_df: pl.DataFrame,
    type_dist_df: pl.DataFrame,
    translation_df: pl.DataFrame,
) -> TagStatisticsView:
    return TagStatisticsView(
        summary_text=_build_summary_text(general_stats),
        distribution=_build_distribution_chart(type_dist_df),
        usage=_build_usage_chart(usage_df),
        language=_build_language_chart(translation_df),
    )
