"""genai-tag-db-tools package exports."""

from .core_api import (
    build_downloaded_at_utc,
    convert_tags,
    ensure_databases,
    get_statistics,
    get_tag_formats,
    register_tag,
    search_tags,
)
from .services.tag_search import TagSearcher
from .utils.cleanup_str import TagCleaner

__all__ = [
    "TagCleaner",
    "TagSearcher",
    "build_downloaded_at_utc",
    "convert_tags",
    "ensure_databases",
    "get_statistics",
    "get_tag_formats",
    "initialize_tag_cleaner",
    "initialize_tag_searcher",
    "register_tag",
    "search_tags",
]


def initialize_tag_searcher() -> TagSearcher:
    """Return TagSearcher instance."""
    return TagSearcher()


def initialize_tag_cleaner() -> TagCleaner:
    """Return TagCleaner instance."""
    return TagCleaner()
