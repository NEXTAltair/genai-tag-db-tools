"""
genai-tag-db-tools パッケージ

タグデータベース管理ツール
"""

from .services.tag_search import TagSearcher
from .utils.cleanup_str import TagCleaner

__all__ = ["TagCleaner", "TagSearcher", "initialize_tag_cleaner", "initialize_tag_searcher"]


def initialize_tag_searcher() -> TagSearcher:
    """TagSearcherの初期化"""
    return TagSearcher()


def initialize_tag_cleaner() -> TagCleaner:
    """TagCleanerの初期化"""
    return TagCleaner()
