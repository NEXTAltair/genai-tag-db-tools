"""
genai-tag-db-tools ÑÃ±ü¸

;j¯é¹hÕ¡¯Èêü¢p’Ğ›W~Y
"""

from .services.tag_search import TagSearcher
from .utils.cleanup_str import TagCleaner

__all__ = ["TagSearcher", "TagCleaner", "initialize_tag_searcher", "initialize_tag_cleaner"]


def initialize_tag_searcher() -> TagSearcher:
    """TagSearchern¤ó¹¿ó¹’WfÔY"""
    return TagSearcher()


def initialize_tag_cleaner() -> TagCleaner:
    """TagCleanern¤ó¹¿ó¹’WfÔY"""
    return TagCleaner()