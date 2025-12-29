"""Core tag services without GUI dependencies."""

import logging

from genai_tag_db_tools.db.repository import get_default_reader
from genai_tag_db_tools.services.tag_search import TagSearcher


class TagCoreService:
    """DBのコア検索/変換機能をまとめた軽量サービス"""

    def __init__(self, searcher: TagSearcher | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._searcher = searcher or TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """タグフォーマット一覧を取得する"""
        return self._searcher.get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        """言語一覧を取得する"""
        return self._searcher.get_tag_languages()

    def get_format_id(self, format_name: str) -> int:
        """フォーマット名からIDを取得する"""
        return self._searcher.reader.get_format_id(format_name)

    def convert_tag(self, tag: str, format_id: int) -> str:
        """単一タグを指定フォーマットに変換する
        Note: This method is deprecated. Use core_api.convert_tags() instead.
        """
        from genai_tag_db_tools.core_api import convert_tags

        reader = get_default_reader()
        format_name = self._searcher.reader.get_format_name(format_id) if format_id > 0 else None
        if not format_name:
            return tag
        return convert_tags(reader, tag, format_name)
