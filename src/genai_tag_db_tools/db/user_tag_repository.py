from __future__ import annotations

from collections.abc import Callable
from logging import getLogger

from sqlalchemy import func
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.schema import USER_TAG_ID_OFFSET, UserTag, UserTagStatusPatch


class UserTagRepository:
    """user DB の USER_TAGS / USER_TAG_STATUS_PATCH への書き込みを担当する。"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.logger = getLogger(__name__)
        self._session_factory = session_factory

    def create_user_tag(self, source_tag: str, tag: str) -> int:
        """USER_TAGS にタグを新規作成し tag_id を返す。

        既存の tag (同一 tag 文字列) があれば既存の tag_id を返す。
        tag_id は max(tag_id) + 1 で採番し USER_TAG_ID_OFFSET (1_000_000_000) 以上を保証する。

        Args:
            source_tag: ソースタグ文字列。
            tag: 正規タグ文字列。

        Returns:
            採番または既存の tag_id。
        """
        with self._session_factory() as session:
            existing = session.query(UserTag).filter(UserTag.tag == tag).one_or_none()
            if existing is not None:
                return existing.tag_id

            max_id = session.query(func.max(UserTag.tag_id)).scalar()
            if max_id is None:
                new_id = USER_TAG_ID_OFFSET
            else:
                new_id = max(int(max_id) + 1, USER_TAG_ID_OFFSET)

            assert new_id >= USER_TAG_ID_OFFSET, f"tag_id={new_id} が OFFSET 未満です"

            new_tag = UserTag(tag_id=new_id, source_tag=source_tag, tag=tag)
            session.add(new_tag)
            session.commit()
            return new_id

    def write_patch(
        self,
        target_scope: str,
        target_tag_id: int,
        format_id: int,
        type_id: int,
        alias: bool,
        preferred_scope: str,
        preferred_tag_id: int,
        deprecated: bool = False,
    ) -> None:
        """USER_TAG_STATUS_PATCH に INSERT or UPDATE する。

        既存行 (同一 composite PK) があれば UPDATE。

        Args:
            target_scope: パッチ対象スコープ ("base" or "user")。
            target_tag_id: パッチ対象タグID。
            format_id: フォーマットID。
            type_id: タイプID。
            alias: エイリアスかどうか。
            preferred_scope: 推奨タグスコープ ("base" or "user")。
            preferred_tag_id: 推奨タグID。
            deprecated: 非推奨かどうか。
        """
        with self._session_factory() as session:
            existing = (
                session.query(UserTagStatusPatch)
                .filter(
                    UserTagStatusPatch.target_scope == target_scope,
                    UserTagStatusPatch.target_tag_id == target_tag_id,
                    UserTagStatusPatch.format_id == format_id,
                )
                .one_or_none()
            )

            if existing is not None:
                existing.type_id = type_id
                existing.alias = alias
                existing.preferred_scope = preferred_scope
                existing.preferred_tag_id = preferred_tag_id
                existing.deprecated = deprecated
            else:
                patch = UserTagStatusPatch(
                    target_scope=target_scope,
                    target_tag_id=target_tag_id,
                    format_id=format_id,
                    type_id=type_id,
                    alias=alias,
                    preferred_scope=preferred_scope,
                    preferred_tag_id=preferred_tag_id,
                    deprecated=deprecated,
                )
                session.add(patch)

            session.commit()
