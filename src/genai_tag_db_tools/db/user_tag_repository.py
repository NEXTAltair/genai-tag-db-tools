from __future__ import annotations

from collections.abc import Callable
from logging import getLogger

from sqlalchemy import func
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    LocalFeedbackApplication,
    TagFormat,
    TagTypeFormatMapping,
    TagTypeName,
    UserTag,
    UserTagStatusPatch,
    UserTagTranslationPatch,
    UserTagUsagePatch,
)


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

        Raises:
            ValueError: tag / source_tag が空の場合（空の tag row を作らない）。
        """
        missing_fields = [name for name, value in (("tag", tag), ("source_tag", source_tag)) if not value]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

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

    def write_translation_patch(
        self, target_scope: str, target_tag_id: int, language: str, translation: str
    ) -> None:
        """USER_TAG_TRANSLATION_PATCH に翻訳を追加する（重複は無視）。

        Args:
            target_scope: パッチ対象スコープ ("base" or "user")。
            target_tag_id: パッチ対象タグID。
            language: 言語コード（例: ja）。
            translation: 翻訳文字列。
        """
        with self._session_factory() as session:
            existing = (
                session.query(UserTagTranslationPatch)
                .filter(
                    UserTagTranslationPatch.target_scope == target_scope,
                    UserTagTranslationPatch.target_tag_id == target_tag_id,
                    UserTagTranslationPatch.language == language,
                    UserTagTranslationPatch.translation == translation,
                )
                .one_or_none()
            )
            if existing is not None:
                return
            session.add(
                UserTagTranslationPatch(
                    target_scope=target_scope,
                    target_tag_id=target_tag_id,
                    language=language,
                    translation=translation,
                )
            )
            session.commit()

    def write_usage_patch(self, target_scope: str, target_tag_id: int, format_id: int, count: int) -> None:
        """USER_TAG_USAGE_PATCH に usage count を INSERT or UPDATE する。

        Args:
            target_scope: パッチ対象スコープ ("base" or "user")。
            target_tag_id: パッチ対象タグID。
            format_id: フォーマットID。
            count: 使用回数。
        """
        with self._session_factory() as session:
            existing = (
                session.query(UserTagUsagePatch)
                .filter(
                    UserTagUsagePatch.target_scope == target_scope,
                    UserTagUsagePatch.target_tag_id == target_tag_id,
                    UserTagUsagePatch.format_id == format_id,
                )
                .one_or_none()
            )
            if existing is not None:
                existing.count = count
            else:
                session.add(
                    UserTagUsagePatch(
                        target_scope=target_scope,
                        target_tag_id=target_tag_id,
                        format_id=format_id,
                        count=count,
                    )
                )
            session.commit()

    def get_format_id(self, format_name: str) -> int | None:
        """user DB 内の TAG_FORMATS から format_id を取得する。"""
        with self._session_factory() as session:
            row = (
                session.query(TagFormat.format_id)
                .filter(TagFormat.format_name == format_name)
                .one_or_none()
            )
            return int(row[0]) if row else None

    def get_or_create_format_id(self, format_name: str, format_id: int | None = None) -> int:
        """user DB 内の TAG_FORMATS から format_id を取得し、無ければ作る。"""
        with self._session_factory() as session:
            existing = session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
            if existing is not None:
                if format_id is not None and int(existing.format_id) != format_id:
                    raise ValueError(
                        f"format_name={format_name!r} already exists with format_id={existing.format_id}, "
                        f"not {format_id}"
                    )
                return int(existing.format_id)
            if format_id is not None:
                id_owner = session.query(TagFormat).filter(TagFormat.format_id == format_id).one_or_none()
                if id_owner is not None and id_owner.format_name != format_name:
                    raise ValueError(
                        f"format_id={format_id} already belongs to format_name={id_owner.format_name!r}"
                    )
                next_id = format_id
            else:
                max_id = session.query(func.max(TagFormat.format_id)).scalar()
                next_id = 1000 if max_id is None else max(int(max_id) + 1, 1000)
            session.add(
                TagFormat(
                    format_id=next_id,
                    format_name=format_name,
                    description=f"Auto-created local feedback format: {format_name}",
                )
            )
            session.commit()
            return next_id

    def get_or_create_type_id(self, format_id: int, type_name: str, type_id: int | None = None) -> int:
        """user DB 内の type mapping を取得し、無ければ作る。"""
        with self._session_factory() as session:
            type_name_row = (
                session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            )
            if type_name_row is None:
                max_type_name_id = session.query(func.max(TagTypeName.type_name_id)).scalar()
                type_name_id = 0 if max_type_name_id is None else int(max_type_name_id) + 1
                type_name_row = TagTypeName(
                    type_name_id=type_name_id,
                    type_name=type_name,
                    description=f"Auto-created local feedback type: {type_name}",
                )
                session.add(type_name_row)
                session.flush()

            existing = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_name_id == type_name_row.type_name_id,
                )
                .order_by(TagTypeFormatMapping.type_id)
                .first()
            )
            if existing is not None:
                return int(existing.type_id)

            if type_id is None:
                if type_name == "unknown":
                    type_id = 0
                else:
                    max_type_id = (
                        session.query(func.max(TagTypeFormatMapping.type_id))
                        .filter(TagTypeFormatMapping.format_id == format_id)
                        .scalar()
                    )
                    type_id = 1 if max_type_id is None else max(int(max_type_id) + 1, 1)

            id_owner = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_id == type_id,
                )
                .one_or_none()
            )
            if id_owner is not None:
                if id_owner.type_name_id == type_name_row.type_name_id:
                    return int(id_owner.type_id)
                owner_name = (
                    session.query(TagTypeName.type_name)
                    .filter(TagTypeName.type_name_id == id_owner.type_name_id)
                    .scalar()
                )
                raise ValueError(
                    f"type_id={type_id} for format_id={format_id} already belongs to "
                    f"type_name={owner_name!r}"
                )

            session.add(
                TagTypeFormatMapping(
                    format_id=format_id,
                    type_id=type_id,
                    type_name_id=type_name_row.type_name_id,
                    description=f"Auto-created local feedback mapping: {format_id}/{type_name}",
                )
            )
            session.commit()
            return int(type_id)

    def get_type_id(self, format_id: int, type_name: str) -> int | None:
        """user DB 内の既存 type mapping から type_id を取得する。"""
        with self._session_factory() as session:
            row = (
                session.query(TagTypeFormatMapping.type_id)
                .join(TagTypeName, TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeName.type_name == type_name,
                )
                .order_by(TagTypeFormatMapping.type_id)
                .first()
            )
            return int(row[0]) if row else None

    def get_type_name_for_type_id(self, format_id: int, type_id: int) -> str | None:
        """user DB 内の既存 type mapping から type_id の所有 type_name を取得する。"""
        with self._session_factory() as session:
            row = (
                session.query(TagTypeName.type_name)
                .join(TagTypeFormatMapping, TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_id == type_id,
                )
                .one_or_none()
            )
            return str(row[0]) if row else None

    def get_status_patch(
        self,
        target_scope: str,
        target_tag_id: int,
        format_id: int,
    ) -> UserTagStatusPatch | None:
        """既存の status patch を detached 風に返す。"""
        with self._session_factory() as session:
            row = (
                session.query(UserTagStatusPatch)
                .filter(
                    UserTagStatusPatch.target_scope == target_scope,
                    UserTagStatusPatch.target_tag_id == target_tag_id,
                    UserTagStatusPatch.format_id == format_id,
                )
                .one_or_none()
            )
            if row is None:
                return None
            return UserTagStatusPatch(
                target_scope=row.target_scope,
                target_tag_id=row.target_tag_id,
                format_id=row.format_id,
                type_id=row.type_id,
                alias=row.alias,
                preferred_scope=row.preferred_scope,
                preferred_tag_id=row.preferred_tag_id,
                deprecated=row.deprecated,
                deprecated_at=row.deprecated_at,
            )

    def has_applied_feedback(self, proposal_hash: str) -> bool:
        with self._session_factory() as session:
            return (
                session.query(LocalFeedbackApplication.application_id)
                .filter(
                    LocalFeedbackApplication.proposal_hash == proposal_hash,
                    LocalFeedbackApplication.status == "applied",
                )
                .first()
                is not None
            )

    def record_feedback_application(
        self,
        *,
        proposal_hash: str,
        proposal_kind: str,
        target_kind: str,
        target_scope: str | None,
        target_tag_id: int | None,
        format_name: str | None,
        field: str | None,
        approved_by: str,
        approved_at,
        status: str,
        dry_run: bool,
        proposal_json: str,
        before_json: str | None,
        after_json: str | None,
        error_message: str | None = None,
    ) -> LocalFeedbackApplication:
        with self._session_factory() as session:
            row = LocalFeedbackApplication(
                proposal_hash=proposal_hash,
                proposal_kind=proposal_kind,
                target_kind=target_kind,
                target_scope=target_scope,
                target_tag_id=target_tag_id,
                format_name=format_name,
                field=field,
                approved_by=approved_by,
                approved_at=approved_at,
                status=status,
                dry_run=dry_run,
                proposal_json=proposal_json,
                before_json=before_json,
                after_json=after_json,
                error_message=error_message,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_feedback_applications(self) -> list[LocalFeedbackApplication]:
        with self._session_factory() as session:
            return (
                session.query(LocalFeedbackApplication)
                .order_by(LocalFeedbackApplication.application_id)
                .all()
            )
