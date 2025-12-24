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
class PieSliceData:
    label: str
    value: float


@dataclass(frozen=True)
class PieChartData:
    title: str
    slices: list[PieSliceData]


@dataclass(frozen=True)
class TagStatisticsView:
    summary_text: str
    distribution: BarChartData | None
    usage: PieChartData | None
    language: BarChartData | None
    top_tags: list[str]


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
    return f"total_tags: {total_tags}\nalias_tags: {alias_tags}\nnon_alias_tags: {non_alias_tags}\n"


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


def _build_usage_chart(usage_df: pl.DataFrame) -> PieChartData | None:
    if usage_df.is_empty():
        return None

    grouped = usage_df.group_by("format_name").agg([pl.col("usage_count").sum().alias("total_usage")])
    slices = [
        PieSliceData(label=row["format_name"], value=_safe_float(row["total_usage"]))
        for row in grouped.iter_rows(named=True)
    ]
    return PieChartData(title="Usage by Format", slices=slices)


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


def _build_top_tags(usage_df: pl.DataFrame) -> list[str]:
    if usage_df.is_empty():
        return []

    grouped = usage_df.group_by("tag_id").agg([pl.col("usage_count").sum().alias("sum_usage")])
    top_10 = grouped.sort("sum_usage", descending=True).head(10)
    items: list[str] = []
    for row in top_10.iter_rows(named=True):
        items.append(f"TagID={row['tag_id']}, usage={row['sum_usage']}")
    return items


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
        top_tags=_build_top_tags(usage_df),
    )
