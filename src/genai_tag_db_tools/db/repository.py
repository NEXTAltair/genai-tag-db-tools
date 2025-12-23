from collections.abc import Callable
from datetime import datetime
from logging import getLogger

import polars as pl
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_

from genai_tag_db_tools.db.schema import (
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
)
from genai_tag_db_tools.utils.messages import ErrorMessages


class TagRepository:
    """タグDBの読み書きをまとめたリポジトリ。"""

    def __init__(self, session_factory: Callable[[], Session] | None = None):
        self.logger = getLogger(__name__)
        if session_factory is not None:
            self.session_factory = session_factory
        else:
            from genai_tag_db_tools.db.runtime import get_session_factory

            self.session_factory = get_session_factory()

    # --- TAG CRUD ---
    def create_tag(self, source_tag: str, tag: str) -> int:
        """(source_tag, tag) を登録し、tag_id を返す。既存なら既存IDを返す。"""
        missing_fields: list[str] = []
        if not tag:
            missing_fields.append("tag")
        if not source_tag:
            missing_fields.append("source_tag")

        if missing_fields:
            msg = ErrorMessages.MISSING_REQUIRED_FIELDS.format(fields=", ".join(missing_fields))
            self.logger.error(msg)
            raise ValueError(msg)

        existing_id = self.get_tag_id_by_name(tag, partial=False)
        if existing_id is not None:
            return existing_id

        new_tag_data = {"source_tag": source_tag, "tag": tag}
        df = pl.DataFrame(new_tag_data)
        self.bulk_insert_tags(df)

        tag_id = self.get_tag_id_by_name(tag, partial=False)
        if tag_id is None:
            msg = ErrorMessages.TAG_ID_NOT_FOUND_AFTER_INSERT
            self.logger.error(msg)
            raise ValueError(msg)
        return tag_id

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        """タグ名でtag_idを検索する。'*' はワイルドカードとして扱う。"""
        if "*" in keyword:
            keyword = keyword.replace("*", "%")

        with self.session_factory() as session:
            query = session.query(Tag)

            if partial or "%" in keyword:
                if not keyword.startswith("%"):
                    keyword = "%" + keyword
                if not keyword.endswith("%"):
                    keyword = keyword + "%"
                query = query.filter(Tag.tag.like(keyword))
            else:
                query = query.filter(Tag.tag == keyword)

            results = query.all()

            if not results:
                return None
            if len(results) == 1:
                return results[0].tag_id

            if partial or "%" in keyword:
                return results[0].tag_id

            raise ValueError(f"複数ヒット: {results}")

    def get_tag_by_id(self, tag_id: int) -> Tag | None:
        """tag_idからTagを取得する。"""
        with self.session_factory() as session:
            return session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()

    def update_tag(self, tag_id: int, *, source_tag: str | None = None, tag: str | None = None) -> None:
        """tag_idを指定してタグ情報を更新する。"""
        with self.session_factory() as session:
            tag_obj = session.get(Tag, tag_id)
            if not tag_obj:
                raise ValueError(f"存在しないタグID {tag_id} の更新を試みました")
            if source_tag is not None:
                tag_obj.source_tag = source_tag
            if tag is not None:
                tag_obj.tag = tag
            session.commit()

    def delete_tag(self, tag_id: int) -> None:
        """tag_idを指定してタグを削除する（注意）。"""
        with self.session_factory() as session:
            tag_obj = session.get(Tag, tag_id)
            if not tag_obj:
                msg = ErrorMessages.INVALID_TAG_ID_DELETION_ATTEMPT.format(tag_id=tag_id)
                self.logger.error(msg)
                raise ValueError(msg)
            session.delete(tag_obj)
            session.commit()

    def list_tags(self) -> list[Tag]:
        """TAGSに登録済みの全タグを取得する。"""
        with self.session_factory() as session:
            return session.query(Tag).all()

    def bulk_insert_tags(self, df: pl.DataFrame) -> None:
        """(source_tag, tag) を一括登録する。既存タグはスキップする。"""
        required_cols = {"source_tag", "tag"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            raise ValueError(f"DataFrameに{missing}カラムがありません")

        unique_tag_list = df["tag"].unique().to_list()
        existing_tag_map = self._fetch_existing_tags_as_map(unique_tag_list)

        new_df = df.filter(~pl.col("tag").is_in(list(existing_tag_map.keys())))
        new_df = new_df.unique(subset=["tag"], keep="first")
        if new_df.is_empty():
            return

        records = new_df.select(["source_tag", "tag"]).to_dicts()
        with self.session_factory() as session:
            try:
                session.bulk_insert_mappings(Tag, records)
                session.commit()
            except IntegrityError as e:
                session.rollback()
                msg = ErrorMessages.DB_OPERATION_FAILED.format(error_msg=str(e))
                raise ValueError(msg) from e

    def get_max_tag_id(self) -> int:
        """現在の最大tag_idを返す。"""
        with self.session_factory() as session:
            max_id = session.query(func.max(Tag.tag_id)).scalar()
            return int(max_id) if max_id is not None else 0

    def create_tag_with_id(self, tag_id: int, source_tag: str, tag: str) -> int:
        """指定したtag_idでタグを作成する。既存ならそのまま返す。"""
        if not tag or not source_tag:
            msg = ErrorMessages.MISSING_REQUIRED_FIELDS.format(fields="source_tag, tag")
            self.logger.error(msg)
            raise ValueError(msg)

        with self.session_factory() as session:
            existing_by_id = session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()
            if existing_by_id:
                if existing_by_id.tag != tag:
                    raise ValueError(f"tag_id={tag_id} は既に '{existing_by_id.tag}' で使用されています。")
                return existing_by_id.tag_id

            existing_by_tag = session.query(Tag).filter(Tag.tag == tag).one_or_none()
            if existing_by_tag:
                if existing_by_tag.tag_id != tag_id:
                    raise ValueError(f"tag='{tag}' は別のtag_id={existing_by_tag.tag_id}で存在します。")
                return existing_by_tag.tag_id

            try:
                session.add(Tag(tag_id=tag_id, source_tag=source_tag, tag=tag))
                session.commit()
                return tag_id
            except IntegrityError as e:
                session.rollback()
                msg = ErrorMessages.DB_OPERATION_FAILED.format(error_msg=str(e))
                raise ValueError(msg) from e

    def ensure_tag_with_id(self, tag_id: int, source_tag: str, tag: str) -> int:
        """tag_idが無ければ作成する。存在すればそのまま返す。"""
        existing = self.get_tag_by_id(tag_id)
        if existing:
            return existing.tag_id
        return self.create_tag_with_id(tag_id, source_tag, tag)

    def _fetch_existing_tags_as_map(self, tag_list: list[str]) -> dict[str, int]:
        """既存タグを {tag: tag_id} で返す。"""
        with self.session_factory() as session:
            existing_tags = session.query(Tag.tag, Tag.tag_id).filter(Tag.tag.in_(tag_list)).all()
            return {tag: tag_id for tag, tag_id in existing_tags}

    # --- TAG_FORMATS ---
    def get_format_id(self, format_name: str) -> int:
        """format_name から format_id を取得する。存在しない場合は 0。"""
        with self.session_factory() as session:
            format_obj = session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
            return format_obj.format_id if format_obj else 0

    def get_format_name(self, format_id: int) -> str | None:
        """format_id から format_name を取得する。"""
        with self.session_factory() as session:
            format_obj = session.query(TagFormat).filter(TagFormat.format_id == format_id).one_or_none()
            return format_obj.format_name if format_obj else None

    # --- TAG_TYPE_FORMAT_MAPPING ---
    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        """(format_id, type_id) から type_name を取得する。"""
        with self.session_factory() as session:
            mapping_obj = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_id == type_id,
                )
                .one_or_none()
            )
            if not mapping_obj:
                return None
            return mapping_obj.type_name.type_name if mapping_obj.type_name else None

    # --- TAG_TYPE_NAME ---
    def get_type_id(self, type_name: str) -> int | None:
        """type_name から type_id を取得する。"""
        with self.session_factory() as session:
            type_obj = session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            return type_obj.type_name_id if type_obj else None

    # --- TAG_STATUS ---
    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        """(tag_id, format_id) の TagStatus を取得する。"""
        with self.session_factory() as session:
            return (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )

    def update_tag_status(
        self,
        tag_id: int,
        format_id: int,
        alias: bool,
        preferred_tag_id: int,
        type_id: int | None = None,
        *,
        deprecated: bool | None = None,
        deprecated_at: datetime | None = None,
        source_created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """TagStatusをINSERT/UPDATEする。"""
        if not alias and preferred_tag_id != tag_id:
            msg = ErrorMessages.DB_OPERATION_FAILED.format(
                error_msg="alias=Falseの場合、preferred_tag_idはtag_idと一致が必須です。",
            )
            raise ValueError(msg)

        with self.session_factory() as session:
            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )

            effective_type_id = (
                type_id if type_id is not None else (status_obj.type_id if status_obj else 0)
            )

            if type_id is not None:
                mapping = (
                    session.query(TagTypeFormatMapping)
                    .filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeFormatMapping.type_id == type_id,
                    )
                    .first()
                )
                if not mapping:
                    msg = ErrorMessages.DB_OPERATION_FAILED.format(
                        error_msg=(
                            f"format_id={format_id}, type_id={type_id} は "
                            "TAG_TYPE_FORMAT_MAPPING に存在しません"
                        )
                    )
                    raise ValueError(msg)

            if status_obj:
                status_obj.type_id = effective_type_id
                status_obj.alias = alias
                status_obj.preferred_tag_id = preferred_tag_id
                if deprecated is not None:
                    status_obj.deprecated = deprecated
                if deprecated_at is not None:
                    status_obj.deprecated_at = deprecated_at
                if source_created_at is not None:
                    status_obj.source_created_at = source_created_at
                if updated_at is not None:
                    status_obj.updated_at = updated_at
                session.commit()
                return

            try:
                status_obj = TagStatus(
                    tag_id=tag_id,
                    format_id=format_id,
                    type_id=effective_type_id,
                    alias=alias,
                    preferred_tag_id=preferred_tag_id,
                    deprecated=deprecated if deprecated is not None else False,
                    deprecated_at=deprecated_at,
                    source_created_at=source_created_at,
                )
                session.add(status_obj)
                session.commit()
            except IntegrityError as e:
                session.rollback()
                msg = ErrorMessages.DB_OPERATION_FAILED.format(error_msg=str(e))
                raise ValueError(msg) from e

    def delete_tag_status(self, tag_id: int, format_id: int) -> None:
        """(tag_id, format_id) の TagStatus を削除する。"""
        with self.session_factory() as session:
            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )
            if status_obj:
                session.delete(status_obj)
                session.commit()

    def list_tag_statuses(self, tag_id: int | None = None) -> list[TagStatus]:
        """TagStatusを一覧取得する。"""
        with self.session_factory() as session:
            query = session.query(TagStatus)
            if tag_id is not None:
                query = query.filter(TagStatus.tag_id == tag_id)
            return query.all()

    # --- TAG_USAGE_COUNTS ---
    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        """TAG_USAGE_COUNTSから使用回数を取得する。"""
        with self.session_factory() as session:
            usage_obj = (
                session.query(TagUsageCounts)
                .filter(TagUsageCounts.tag_id == tag_id, TagUsageCounts.format_id == format_id)
                .one_or_none()
            )
            return usage_obj.count if usage_obj else None

    def list_usage_counts(
        self, tag_id: int | None = None, format_id: int | None = None
    ) -> list[TagUsageCounts]:
        """TAG_USAGE_COUNTSを一覧取得する。"""
        with self.session_factory() as session:
            query = session.query(TagUsageCounts)
            if tag_id is not None:
                query = query.filter(TagUsageCounts.tag_id == tag_id)
            if format_id is not None:
                query = query.filter(TagUsageCounts.format_id == format_id)
            return query.all()

    def update_usage_count(
        self,
        tag_id: int,
        format_id: int,
        count: int,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        """TAG_USAGE_COUNTSをINSERT/UPDATEする。"""
        with self.session_factory() as session:
            usage_obj = (
                session.query(TagUsageCounts)
                .filter(TagUsageCounts.tag_id == tag_id, TagUsageCounts.format_id == format_id)
                .one_or_none()
            )

            if usage_obj:
                usage_obj.count = count
                if observed_at is not None:
                    usage_obj.updated_at = observed_at
            else:
                usage_obj = TagUsageCounts(tag_id=tag_id, format_id=format_id, count=count)
                if observed_at is not None:
                    usage_obj.updated_at = observed_at
                session.add(usage_obj)
            session.commit()

    # --- TAG_TRANSLATIONS ---
    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        """tag_idの翻訳情報を取得する。"""
        with self.session_factory() as session:
            return session.query(TagTranslation).filter(TagTranslation.tag_id == tag_id).all()

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        """翻訳を追加または更新する。"""
        with self.session_factory() as session:
            tag = session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()
            if not tag:
                raise ValueError(f"存在しないタグID: {tag_id}")

            existing = (
                session.query(TagTranslation)
                .filter(
                    TagTranslation.tag_id == tag_id,
                    TagTranslation.language == language,
                    TagTranslation.translation == translation,
                )
                .one_or_none()
            )
            if existing:
                return

            try:
                translation_obj = TagTranslation(tag_id=tag_id, language=language, translation=translation)
                session.add(translation_obj)
                session.commit()
            except IntegrityError as e:
                session.rollback()
                raise ValueError(f"DB操作に失敗しました: {e}") from e

    # --- 検索 ---
    def search_tag_ids(self, keyword: str, partial: bool = False) -> list[int]:
        """tag/source_tag/translationからtag_idを検索する。"""
        if "*" in keyword:
            keyword = keyword.replace("*", "%")

        with self.session_factory() as session:
            tag_query = session.query(Tag.tag_id)
            translation_query = session.query(TagTranslation.tag_id)

            if partial or "%" in keyword:
                if not keyword.startswith("%"):
                    keyword = "%" + keyword
                if not keyword.endswith("%"):
                    keyword = keyword + "%"

            tag_conditions = or_(
                Tag.tag.like(keyword) if partial or "%" in keyword else Tag.tag == keyword,
                Tag.source_tag.like(keyword) if partial or "%" in keyword else Tag.source_tag == keyword,
            )
            tag_query = tag_query.filter(tag_conditions)

            translation_condition = (
                TagTranslation.translation.like(keyword)
                if partial or "%" in keyword
                else TagTranslation.translation == keyword
            )
            translation_query = translation_query.filter(translation_condition)

            tag_ids = {row[0] for row in tag_query.all()}
            translation_ids = {row[0] for row in translation_query.all()}

            return list(tag_ids | translation_ids)

    def search_tags(
        self,
        keyword: str,
        *,
        partial: bool = False,
        format_name: str | None = None,
        type_name: str | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
        resolve_preferred: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]:
        """検索結果を辞書配列で返す。"""
        if "*" in keyword:
            keyword = keyword.replace("*", "%")

        with self.session_factory() as session:
            tag_query = session.query(Tag.tag_id)
            translation_query = session.query(TagTranslation.tag_id)

            if partial or "%" in keyword:
                if not keyword.startswith("%"):
                    keyword = "%" + keyword
                if not keyword.endswith("%"):
                    keyword = keyword + "%"

            tag_conditions = or_(
                Tag.tag.like(keyword) if partial or "%" in keyword else Tag.tag == keyword,
                Tag.source_tag.like(keyword) if partial or "%" in keyword else Tag.source_tag == keyword,
            )
            tag_query = tag_query.filter(tag_conditions)

            translation_condition = (
                TagTranslation.translation.like(keyword)
                if partial or "%" in keyword
                else TagTranslation.translation == keyword
            )
            translation_query = translation_query.filter(translation_condition)

            tag_ids = {row[0] for row in tag_query.all()}
            translation_ids = {row[0] for row in translation_query.all()}
            tag_ids |= translation_ids
            if not tag_ids:
                return []

            format_id = 0
            if format_name and format_name.lower() != "all":
                fmt_obj = (
                    session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
                )
                if not fmt_obj:
                    return []
                format_id = fmt_obj.format_id
                format_tag_ids = {
                    row[0]
                    for row in session.query(TagStatus.tag_id)
                    .filter(TagStatus.format_id == format_id)
                    .all()
                }
                tag_ids &= format_tag_ids
                if not tag_ids:
                    return []

            if min_usage is not None or max_usage is not None:
                usage_query = session.query(TagUsageCounts.tag_id)
                if format_id:
                    usage_query = usage_query.filter(TagUsageCounts.format_id == format_id)
                if min_usage is not None:
                    usage_query = usage_query.filter(TagUsageCounts.count >= min_usage)
                if max_usage is not None:
                    usage_query = usage_query.filter(TagUsageCounts.count <= max_usage)
                usage_tag_ids = {row[0] for row in usage_query.all()}
                tag_ids &= usage_tag_ids
                if not tag_ids:
                    return []

            if type_name and type_name.lower() != "all":
                type_obj = (
                    session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
                )
                if not type_obj:
                    return []
                type_query = session.query(TagStatus.tag_id).join(
                    TagTypeFormatMapping,
                    (TagStatus.format_id == TagTypeFormatMapping.format_id)
                    & (TagStatus.type_id == TagTypeFormatMapping.type_id),
                )
                type_query = type_query.filter(TagTypeFormatMapping.type_name_id == type_obj.type_name_id)
                if format_id:
                    type_query = type_query.filter(TagStatus.format_id == format_id)
                type_tag_ids = {row[0] for row in type_query.all()}
                tag_ids &= type_tag_ids
                if not tag_ids:
                    return []

            if alias is not None:
                alias_query = session.query(TagStatus.tag_id).filter(TagStatus.alias == alias)
                if format_id:
                    alias_query = alias_query.filter(TagStatus.format_id == format_id)
                alias_tag_ids = {row[0] for row in alias_query.all()}
                tag_ids &= alias_tag_ids
                if not tag_ids:
                    return []

            if language and language.lower() != "all":
                lang_query = session.query(TagTranslation.tag_id).filter(
                    TagTranslation.language == language
                )
                lang_tag_ids = {row[0] for row in lang_query.all()}
                tag_ids &= lang_tag_ids
                if not tag_ids:
                    return []

            rows: list[dict] = []
            for t_id in sorted(tag_ids):
                tag_obj = session.query(Tag).filter(Tag.tag_id == t_id).one_or_none()
                if not tag_obj:
                    continue

                usage_count = 0
                is_alias = False
                resolved_type_name = ""
                preferred_tag_id = t_id

                if format_id:
                    status_obj = (
                        session.query(TagStatus)
                        .filter(TagStatus.tag_id == t_id, TagStatus.format_id == format_id)
                        .one_or_none()
                    )
                    if status_obj:
                        if status_obj.alias is None:
                            self.logger.warning(
                                "[search_tags] alias=NULL detected (tag_id=%s, format_id=%s).",
                                t_id,
                                format_id,
                            )
                            continue
                        is_alias = status_obj.alias
                        preferred_tag_id = status_obj.preferred_tag_id
                        type_mapping = (
                            session.query(TagTypeFormatMapping)
                            .filter(
                                TagTypeFormatMapping.format_id == format_id,
                                TagTypeFormatMapping.type_id == status_obj.type_id,
                            )
                            .one_or_none()
                        )
                        if type_mapping and type_mapping.type_name:
                            resolved_type_name = type_mapping.type_name.type_name

                    usage_obj = (
                        session.query(TagUsageCounts)
                        .filter(TagUsageCounts.tag_id == t_id, TagUsageCounts.format_id == format_id)
                        .one_or_none()
                    )
                    usage_count = usage_obj.count if usage_obj else 0

                resolved_tag_id = t_id
                if resolve_preferred and format_id and preferred_tag_id != t_id:
                    preferred_obj = session.query(Tag).filter(Tag.tag_id == preferred_tag_id).one_or_none()
                    if preferred_obj:
                        tag_obj = preferred_obj
                        resolved_tag_id = preferred_tag_id

                trans_dict: dict[str, list[str]] = {}
                translations = (
                    session.query(TagTranslation).filter(TagTranslation.tag_id == resolved_tag_id).all()
                )
                for tr in translations:
                    if tr.language and tr.translation:
                        trans_dict.setdefault(tr.language, []).append(tr.translation)

                rows.append(
                    {
                        "tag_id": resolved_tag_id,
                        "tag": tag_obj.tag,
                        "source_tag": tag_obj.source_tag,
                        "usage_count": usage_count,
                        "alias": is_alias,
                        "type_name": resolved_type_name,
                        "translations": trans_dict,
                    }
                )

            if offset is not None:
                rows = rows[offset:]
            if limit is not None:
                rows = rows[:limit]

            return rows

    _LEGACY_SEARCH_HELPERS = """
    def search_tag_ids_by_usage_count_range(self, min_count=None, max_count=None, format_id=None):
        ...

    def search_tag_ids_by_alias(self, alias=True, format_id=None):
        ...

    def search_tag_ids_by_type_name(self, type_name, format_id=None):
        ...

    def search_tag_ids_by_format_name(self, format_name):
        ...

    def find_preferred_tag(self, tag_id, format_id):
        ...
    """

    def get_all_tag_ids(self) -> list[int]:
        """全tag_idを取得する。"""
        with self.session_factory() as session:
            return [tag.tag_id for tag in session.query(Tag).all()]

    def get_tag_format_ids(self) -> list[int]:
        """全format_idを取得する。"""
        with self.session_factory() as session:
            tag_ids = session.query(TagFormat.format_id).distinct().all()
            return [tag_id[0] for tag_id in tag_ids]

    def get_tag_formats(self) -> list[str]:
        """全format_nameを取得する。"""
        with self.session_factory() as session:
            formats = session.query(TagFormat.format_name).distinct().all()
            return [format[0] for format in formats]

    def get_format_map(self) -> dict[int, str]:
        """format_id -> format_name を返す。"""
        with self.session_factory() as session:
            rows = session.query(TagFormat.format_id, TagFormat.format_name).all()
            return {format_id: format_name for format_id, format_name in rows}

    def get_tag_languages(self) -> list[str]:
        """全languageを取得する。"""
        with self.session_factory() as session:
            languages = session.query(TagTranslation.language).distinct().all()
            return [lang[0] for lang in languages]

    def get_tag_types(self, format_id: int) -> list[str]:
        """format_idに紐づくタイプ名一覧を取得する。"""
        with self.session_factory() as session:
            rows = (
                session.query(TagTypeName.type_name)
                .join(TagTypeFormatMapping, TagTypeName.type_name_id == TagTypeFormatMapping.type_name_id)
                .filter(TagTypeFormatMapping.format_id == format_id)
                .all()
            )
        return [row[0] for row in rows]

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
        """(format_id, type_id) -> type_name を返す。"""
        with self.session_factory() as session:
            rows = (
                session.query(
                    TagTypeFormatMapping.format_id,
                    TagTypeFormatMapping.type_id,
                    TagTypeName.type_name,
                )
                .join(TagTypeName, TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id)
                .all()
            )
            return {(format_id, type_id): type_name for format_id, type_id, type_name in rows}

    def get_all_types(self) -> list[str]:
        """全タイプ名を取得する。"""
        with self.session_factory() as session:
            return [type_obj.type_name for type_obj in session.query(TagTypeName).all()]


class MergedTagReader:
    """base/user DBを統合して読み取りだけ提供するリーダー。"""

    def __init__(
        self,
        base_repo: TagRepository | list[TagRepository],
        user_repo: TagRepository | None = None,
    ):
        self.logger = getLogger(__name__)
        if isinstance(base_repo, list):
            if not base_repo:
                raise ValueError("base_repo は空にできません。")
            self.base_repos = base_repo
        else:
            self.base_repos = [base_repo]
        self.base_repo = self.base_repos[0]
        self.user_repo = user_repo

    def _has_user(self) -> bool:
        return self.user_repo is not None

    def _iter_base_repos(self) -> list[TagRepository]:
        return list(self.base_repos)

    def _iter_base_repos_low_to_high(self) -> list[TagRepository]:
        return list(reversed(self.base_repos))

    def _iter_repos(self) -> list[TagRepository]:
        repos: list[TagRepository] = []
        if self.user_repo is not None:
            repos.append(self.user_repo)
        repos.extend(self.base_repos)
        return repos

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        if self._has_user():
            user_id = self.user_repo.get_tag_id_by_name(keyword, partial=partial)
            if user_id is not None:
                return user_id
        for repo in self._iter_base_repos():
            base_id = repo.get_tag_id_by_name(keyword, partial=partial)
            if base_id is not None:
                return base_id
        return None

    def get_tag_by_id(self, tag_id: int) -> Tag | None:
        if self._has_user():
            tag = self.user_repo.get_tag_by_id(tag_id)
            if tag is not None:
                return tag
        for repo in self._iter_base_repos():
            tag = repo.get_tag_by_id(tag_id)
            if tag is not None:
                return tag
        return None

    def list_tags(self) -> list[Tag]:
        merged: dict[int, Tag] = {}
        for repo in self._iter_base_repos_low_to_high():
            for tag in repo.list_tags():
                merged[tag.tag_id] = tag
        if self._has_user():
            for tag in self.user_repo.list_tags():
                merged[tag.tag_id] = tag
        return list(merged.values())

    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        if self._has_user():
            status = self.user_repo.get_tag_status(tag_id, format_id)
            if status is not None:
                return status
        for repo in self._iter_base_repos():
            status = repo.get_tag_status(tag_id, format_id)
            if status is not None:
                return status
        return None

    def list_tag_statuses(self, tag_id: int | None = None) -> list[TagStatus]:
        merged: dict[tuple[int, int], TagStatus] = {}
        for repo in self._iter_base_repos_low_to_high():
            for status in repo.list_tag_statuses(tag_id=tag_id):
                merged[(status.tag_id, status.format_id)] = status
        if self._has_user():
            for status in self.user_repo.list_tag_statuses(tag_id=tag_id):
                merged[(status.tag_id, status.format_id)] = status
        return list(merged.values())

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        if self._has_user():
            count = self.user_repo.get_usage_count(tag_id, format_id)
            if count is not None:
                return count
        for repo in self._iter_base_repos():
            count = repo.get_usage_count(tag_id, format_id)
            if count is not None:
                return count
        return None

    def list_usage_counts(
        self, tag_id: int | None = None, format_id: int | None = None
    ) -> list[TagUsageCounts]:
        merged: dict[tuple[int, int], TagUsageCounts] = {}
        for repo in self._iter_base_repos_low_to_high():
            for row in repo.list_usage_counts(tag_id=tag_id, format_id=format_id):
                merged[(row.tag_id, row.format_id)] = row
        if self._has_user():
            for row in self.user_repo.list_usage_counts(tag_id=tag_id, format_id=format_id):
                merged[(row.tag_id, row.format_id)] = row
        return list(merged.values())

    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        translations: list[TagTranslation] = []
        for repo in self._iter_base_repos_low_to_high():
            translations += repo.get_translations(tag_id)
        if self._has_user():
            translations += self.user_repo.get_translations(tag_id)

        seen: set[tuple[str, str]] = set()
        unique: list[TagTranslation] = []
        for tr in translations:
            key = (tr.language, tr.translation)
            if key in seen:
                continue
            seen.add(key)
            unique.append(tr)
        return unique

    def search_tag_ids(self, keyword: str, partial: bool = False) -> list[int]:
        tag_ids: set[int] = set()
        for repo in self._iter_base_repos():
            tag_ids |= set(repo.search_tag_ids(keyword, partial=partial))
        if self._has_user():
            tag_ids |= set(self.user_repo.search_tag_ids(keyword, partial=partial))
        return list(tag_ids)

    def search_tags(
        self,
        keyword: str,
        *,
        partial: bool = False,
        format_name: str | None = None,
        type_name: str | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
        resolve_preferred: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]:
        merged: dict[int, dict] = {}
        for repo in self._iter_base_repos_low_to_high():
            rows = repo.search_tags(
                keyword,
                partial=partial,
                format_name=format_name,
                type_name=type_name,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=alias,
                resolve_preferred=resolve_preferred,
                limit=limit,
                offset=offset,
            )
            for row in rows:
                merged[row["tag_id"]] = row
        if self._has_user():
            user_rows = self.user_repo.search_tags(
                keyword,
                partial=partial,
                format_name=format_name,
                type_name=type_name,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=alias,
                resolve_preferred=resolve_preferred,
                limit=limit,
                offset=offset,
            )
            for row in user_rows:
                merged[row["tag_id"]] = row
        return list(merged.values())

    def get_all_tag_ids(self) -> list[int]:
        tag_ids: set[int] = set()
        for repo in self._iter_base_repos():
            tag_ids |= set(repo.get_all_tag_ids())
        if self._has_user():
            tag_ids |= set(self.user_repo.get_all_tag_ids())
        return list(tag_ids)

    def get_tag_formats(self) -> list[str]:
        formats: set[str] = set()
        for repo in self._iter_base_repos():
            formats |= set(repo.get_tag_formats())
        if self._has_user():
            formats |= set(self.user_repo.get_tag_formats())
        return list(formats)

    def get_format_map(self) -> dict[int, str]:
        formats: dict[int, str] = {}
        for repo in self._iter_base_repos_low_to_high():
            formats.update(repo.get_format_map())
        if self._has_user():
            formats.update(self.user_repo.get_format_map())
        return formats

    def get_tag_languages(self) -> list[str]:
        languages: set[str] = set()
        for repo in self._iter_base_repos():
            languages |= set(repo.get_tag_languages())
        if self._has_user():
            languages |= set(self.user_repo.get_tag_languages())
        return list(languages)

    def get_tag_types(self, format_id: int) -> list[str]:
        types: set[str] = set()
        for repo in self._iter_base_repos():
            types |= set(repo.get_tag_types(format_id))
        if self._has_user():
            types |= set(self.user_repo.get_tag_types(format_id))
        return list(types)

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
        mapping: dict[tuple[int, int], str] = {}
        for repo in self._iter_base_repos_low_to_high():
            mapping.update(repo.get_type_mapping_map())
        if self._has_user():
            mapping.update(self.user_repo.get_type_mapping_map())
        return mapping

    def get_all_types(self) -> list[str]:
        types: set[str] = set()
        for repo in self._iter_base_repos():
            types |= set(repo.get_all_types())
        if self._has_user():
            types |= set(self.user_repo.get_all_types())
        return list(types)

    def get_format_id(self, format_name: str) -> int:
        if self._has_user():
            fmt_id = self.user_repo.get_format_id(format_name)
            if fmt_id:
                return fmt_id
        for repo in self._iter_base_repos():
            fmt_id = repo.get_format_id(format_name)
            if fmt_id:
                return fmt_id
        raise ValueError(f"format_name が見つかりません: {format_name}")

    def get_format_name(self, format_id: int) -> str | None:
        if self._has_user():
            name = self.user_repo.get_format_name(format_id)
            if name:
                return name
        for repo in self._iter_base_repos():
            name = repo.get_format_name(format_id)
            if name:
                return name
        return None


def get_default_repository() -> TagRepository | MergedTagReader:
    from genai_tag_db_tools.db.runtime import (
        get_base_session_factories,
        get_user_session_factory_optional,
    )

    base_factories = get_base_session_factories()
    base_repos = [TagRepository(factory) for factory in base_factories]
    user_factory = get_user_session_factory_optional()
    if user_factory is None:
        if len(base_repos) == 1:
            return base_repos[0]
        return MergedTagReader(base_repos)
    return MergedTagReader(base_repos, TagRepository(user_factory))
