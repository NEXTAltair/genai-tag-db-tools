"""
genai-tag-db-tools �ñ��

;�j��hա�����p�ЛW~Y
"""

from .services.tag_search import TagSearcher
from .utils.cleanup_str import TagCleaner

__all__ = ["TagSearcher", "TagCleaner", "initialize_tag_searcher", "initialize_tag_cleaner"]


def initialize_tag_searcher() -> TagSearcher:
    """TagSearchern���Wf�Y"""
    return TagSearcher()


def initialize_tag_cleaner() -> TagCleaner:
    """TagCleanern���Wf�Y"""
    return TagCleaner()