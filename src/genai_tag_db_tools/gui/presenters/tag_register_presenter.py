from __future__ import annotations

import polars as pl

from genai_tag_db_tools.utils.cleanup_str import TagCleaner


def build_tag_info(
    *,
    tag: str,
    source_tag: str,
    format_name: str,
    type_name: str,
    use_count: int,
    language: str,
    translation: str,
) -> dict:
    if not tag and not source_tag:
        raise ValueError("tag or source_tag is required")

    normalized_tag = TagCleaner.clean_tags(source_tag or tag)
    return {
        "normalized_tag": normalized_tag,
        "source_tag": source_tag or tag,
        "format_name": format_name,
        "type_name": type_name,
        "use_count": use_count,
        "language": language,
        "translation": translation,
    }


def format_tag_details(tag_id: int, details_df: pl.DataFrame) -> str:
    if details_df.is_empty():
        return f"TagID {tag_id} not found."

    info = details_df.to_dicts()[0]
    lines = [
        f"Tag Details (ID: {tag_id}):",
        f"tag: {info.get('tag')}",
        f"source_tag: {info.get('source_tag')}",
        f"formats: {info.get('formats')}",
        f"types: {info.get('types')}",
        f"total_usage_count: {info.get('total_usage_count')}",
        f"translations: {info.get('translations')}",
        "-" * 40,
    ]
    return "\n".join(lines)
