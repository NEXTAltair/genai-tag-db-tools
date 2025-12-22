import logging

import polars as pl

from genai_tag_db_tools.db.repository import TagRepository


class TagSearcher:
    """タグ検索・変換などを提供する軽量サービス。"""

    def __init__(self, repository: TagRepository | None = None):
        self.logger = logging.getLogger(__name__)
        self.tag_repo = repository or TagRepository()

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

        rows = self.tag_repo.search_tags(
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
        """指定フォーマットの推奨タグへ変換する。"""
        tag_id = self.tag_repo.get_tag_id_by_name(search_tag, partial=False)
        if tag_id is None:
            return search_tag

        status = self.tag_repo.get_tag_status(tag_id, format_id)
        if not status:
            return search_tag

        preferred_tag_id = status.preferred_tag_id
        if preferred_tag_id == tag_id:
            return search_tag

        preferred_tag_obj = self.tag_repo.get_tag_by_id(preferred_tag_id)
        if not preferred_tag_obj:
            return search_tag

        preferred_tag = preferred_tag_obj.tag
        if preferred_tag == "invalid tag":
            self.logger.warning(
                "[convert_tag] '%s' の推奨先が invalid tag のため変換を回避します。",
                search_tag,
            )
            return search_tag

        if search_tag != preferred_tag:
            self.logger.info("タグ '%s' を '%s' に変換", search_tag, preferred_tag)

        return preferred_tag

    def get_tag_types(self, format_name: str) -> list[str]:
        """フォーマットに紐づくタグタイプ名一覧を取得する。"""
        format_id = self.tag_repo.get_format_id(format_name)
        if not format_id:
            return []
        return self.tag_repo.get_tag_types(format_id)

    def get_all_types(self) -> list[str]:
        """全タイプ名を取得する。"""
        return self.tag_repo.get_all_types()

    def get_tag_languages(self) -> list[str]:
        """登録済み言語一覧を取得する。"""
        return self.tag_repo.get_tag_languages()

    def get_tag_formats(self) -> list[str]:
        """利用可能なフォーマット名一覧を取得する。"""
        return self.tag_repo.get_tag_formats()

    def get_format_id(self, format_name: str | None) -> int:
        """フォーマット名からフォーマットIDを取得する。"""
        if format_name is None:
            return 0
        return self.tag_repo.get_format_id(format_name)
