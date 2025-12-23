from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagSearchQuery:
    keyword: str
    partial: bool
    format_name: str | None
    type_name: str | None
    language: str | None
    min_usage: int | None
    max_usage: int | None
    alias: bool | None = None


def normalize_choice(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.lower() == "all":
        return None
    return trimmed
