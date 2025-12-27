import logging

import polars as pl

from genai_tag_db_tools.db.repository import MergedTagReader, get_default_reader


class TagSearcher:
    """タグ検索・変換などを提供する軽量サービス。"""

    def __init__(self, reader: MergedTagReader | None = None):
        self.logger = logging.getLogger(__name__)
        self.reader = reader or get_default_reader()

    def search_tags(
        self,
        keyword: str,
        partial: bool = False,
        format_name: str | None = None,
        type_name: str | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
        resolve_preferred: bool = False,
    ) -> pl.DataFrame:
        """キーワード条件でタグを検索してDataFrameを返す。"""
        self.logger.info(
            "[search_tags] keyword=%s partial=%s format=%s type=%s lang=%s usage=(%s, %s) alias=%s",
            keyword,
            partial,
            format_name,
            type_name,
            language,
            min_usage,
            max_usage,
            alias,
        )

        rows = self.reader.search_tags(
            keyword,
            partial=partial,
            format_name=format_name,
            type_name=type_name,
            language=language,
            min_usage=min_usage,
            max_usage=max_usage,
            alias=alias,
            resolve_preferred=resolve_preferred,
        )

        if not rows:
            return pl.DataFrame([])
        return pl.DataFrame(rows)

    def convert_tag(self, search_tag: str, format_id: int) -> str:
        """指定フォーマットの推奨タグへ変換する。

        Deprecated: Use core_api.convert_tags() instead.
        """
        raise NotImplementedError(
            "TagSearcher.convert_tag() is deprecated. Use core_api.convert_tags() instead."
        )

    def get_tag_types(self, format_name: str) -> list[str]:
        """フォーマットに紐づくタグタイプ名一覧を取得する。"""
        format_id = self.reader.get_format_id(format_name)
        if not format_id:
            return []
        return self.reader.get_tag_types(format_id)

    def get_all_types(self) -> list[str]:
        """全タイプ名を取得する。"""
        return self.reader.get_all_types()

    def get_tag_languages(self) -> list[str]:
        """登録済み言語一覧を取得する。"""
        return self.reader.get_tag_languages()

    def get_tag_formats(self) -> list[str]:
        """利用可能なフォーマット名一覧を取得する。"""
        return self.reader.get_tag_formats()

    def get_format_id(self, format_name: str | None) -> int:
        """フォーマット名からフォーマットIDを取得する。

        Deprecated: Use core_api.get_tag_formats() and repo.get_format_id() instead.
        """
        raise NotImplementedError(
            "TagSearcher.get_format_id() is deprecated. Use repo.get_format_id() instead."
        )
