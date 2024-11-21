from logging import getLogger
from typing import Optional
from matplotlib.pylab import f
from sqlalchemy.orm import Session
from genai_tag_db_tools.data.database_schema import (
    Tag,
    TagStatus,
    TagTranslation,
    TagFormat,
    TagTypeName,
    TagTypeFormatMapping,
    TagUsageCounts,
)


class TagRepository:
    """タグデータへのアクセスを管理するリポジトリクラス"""

    def __init__(self, session: Session):
        """
        Args:
            session: SQLAlchemyのセッション
        """
        self.logger = getLogger(__name__)
        self.session = session

    def get_tags_by_names(self, tag_names: list[str]) -> list[Tag]:
        """タグ名のリストから対応するタグを取得

        Args:
            tag_names: 検索するタグ名のリスト

        Returns:
            list[Tag]: 見つかったタグのリスト
        """
        return self.session.query(Tag).filter(Tag.tag.in_(tag_names)).all()

    def bulk_insert_tags(self, tag_data: list[dict[str, str]]) -> None:
        """タグを一括登録

        Args:
            tag_data: 登録するタグデータのリスト。各辞書はsource_tagとtagを含む

        Raises:
            Exception: 登録に失敗した場合
        """
        try:
            self.session.bulk_insert_mappings(Tag, tag_data)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            raise

    def get_tag_id_mapping(self, tag_names: list[str]) -> dict[str, int]:
        """タグ名からタグIDへのマッピングを取得

        Args:
            tag_names: マッピングを取得するタグ名のリスト

        Returns:
            dict[str, int]: タグ名をキー、タグIDを値とする辞書
        """
        tags = self.get_tags_by_names(tag_names)
        return {tag.tag: tag.tag_id for tag in tags}
