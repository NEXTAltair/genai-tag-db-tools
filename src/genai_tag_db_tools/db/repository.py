from collections.abc import Callable
from datetime import datetime
from logging import getLogger
from typing import Any

import polars as pl
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.query_utils import (
    TagSearchPreloader,
    TagSearchQueryBuilder,
    TagSearchResultBuilder,
    normalize_search_keyword,
)
from genai_tag_db_tools.db.schema import (
    DatabaseMetadata,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
)
from genai_tag_db_tools.models import TagSearchRow
from genai_tag_db_tools.utils.messages import ErrorMessages

# Reserve format_id range 1-999 for base DBs, 1000+ for user DBs
USER_DB_FORMAT_ID_OFFSET = 1000


class TagReader:
    """Read-only tag database access."""

    def __init__(self, session_factory: Callable[[], Session] | None = None):
        self.logger = getLogger(__name__)
        if session_factory is not None:
            self.session_factory = session_factory
        else:
            from genai_tag_db_tools.db.runtime import get_session_factory

            self.session_factory = get_session_factory()

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        keyword, use_like = normalize_search_keyword(keyword, partial)

        with self.session_factory() as session:
            query = session.query(Tag)

            if use_like:
                query = query.filter(Tag.tag.like(keyword))
            else:
                query = query.filter(Tag.tag == keyword)

            results = query.all()

            if not results:
                return None
            if len(results) == 1:
                return results[0].tag_id

            if use_like:
                return results[0].tag_id

            raise ValueError(f"Multiple tags found: {results}")

    def get_tag_by_id(self, tag_id: int) -> Tag | None:
        with self.session_factory() as session:
            return session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()

    def list_tags(self) -> list[Tag]:
        with self.session_factory() as session:
            return session.query(Tag).all()

    def get_max_tag_id(self) -> int:
        with self.session_factory() as session:
            max_id = session.query(func.max(Tag.tag_id)).scalar()
            return int(max_id) if max_id is not None else 0

    def get_metadata_value(self, key: str) -> str | None:
        with self.session_factory() as session:
            row = session.query(DatabaseMetadata).filter(DatabaseMetadata.key == key).one_or_none()
            return row.value if row else None

    def get_database_version(self) -> str | None:
        return self.get_metadata_value("version")

    def get_format_id(self, format_name: str) -> int:
        with self.session_factory() as session:
            format_obj = session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
            return format_obj.format_id if format_obj else 0

    def get_format_name(self, format_id: int) -> str | None:
        with self.session_factory() as session:
            format_obj = session.query(TagFormat).filter(TagFormat.format_id == format_id).one_or_none()
            return format_obj.format_name if format_obj else None

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
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

    def get_type_id(self, type_name: str) -> int | None:
        with self.session_factory() as session:
            type_obj = session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            return type_obj.type_name_id if type_obj else None

    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        with self.session_factory() as session:
            return (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )

    def list_tag_statuses(self, tag_id: int | None = None) -> list[TagStatus]:
        with self.session_factory() as session:
            query = session.query(TagStatus)
            if tag_id is not None:
                query = query.filter(TagStatus.tag_id == tag_id)
            return query.all()

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
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
        with self.session_factory() as session:
            query = session.query(TagUsageCounts)
            if tag_id is not None:
                query = query.filter(TagUsageCounts.tag_id == tag_id)
            if format_id is not None:
                query = query.filter(TagUsageCounts.format_id == format_id)
            return query.all()

    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        with self.session_factory() as session:
            return session.query(TagTranslation).filter(TagTranslation.tag_id == tag_id).all()

    def list_translations(self) -> list[TagTranslation]:
        with self.session_factory() as session:
            return session.query(TagTranslation).all()

    def search_tag_ids(self, keyword: str, partial: bool = False) -> list[int]:
        keyword, use_like = normalize_search_keyword(keyword, partial)

        with self.session_factory() as session:
            builder = TagSearchQueryBuilder(session)
            tag_ids = builder.initial_tag_ids(keyword, use_like)
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
    ) -> list[TagSearchRow]:
        keyword, use_like = normalize_search_keyword(keyword, partial)

        with self.session_factory() as session:
            builder = TagSearchQueryBuilder(session)
            tag_ids = builder.initial_tag_ids(keyword, use_like)
            if not tag_ids:
                return []

            tag_ids, format_id = builder.apply_format_filter(tag_ids, format_name)
            if not tag_ids:
                return []

            tag_ids = builder.apply_usage_filter(tag_ids, format_id, min_usage, max_usage)
            if not tag_ids:
                return []

            tag_ids = builder.apply_type_filter(tag_ids, format_id, type_name)
            if not tag_ids:
                return []

            tag_ids = builder.apply_alias_filter(tag_ids, format_id, alias)
            if not tag_ids:
                return []

            tag_ids = builder.apply_language_filter(tag_ids, language)
            if not tag_ids:
                return []

            preloader = TagSearchPreloader(session)
            preloaded = preloader.load(tag_ids)

            rows: list[TagSearchRow] = []
            result_builder = TagSearchResultBuilder(
                format_id=format_id,
                resolve_preferred=resolve_preferred,
                logger=self.logger,
            )
            for t_id in sorted(tag_ids):
                row = result_builder.build_row(t_id, preloaded)
                if row is not None:
                    rows.append(row)

            return rows

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, TagSearchRow]:
        cleaned = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
        if not cleaned:
            return {}

        with self.session_factory() as session:
            builder = TagSearchQueryBuilder(session)
            tag_ids_by_keyword = builder.initial_tag_ids_for_keywords(cleaned)
            if not tag_ids_by_keyword:
                return {}

            all_tag_ids: set[int] = set()
            for tag_ids in tag_ids_by_keyword.values():
                all_tag_ids |= set(tag_ids)

            tag_ids, format_id = builder.apply_format_filter(all_tag_ids, format_name)
            if not tag_ids:
                return {}

            preloader = TagSearchPreloader(session)
            preloaded = preloader.load(tag_ids)
            result_builder = TagSearchResultBuilder(
                format_id=format_id,
                resolve_preferred=resolve_preferred,
                logger=self.logger,
            )

            row_by_input_id: dict[int, TagSearchRow] = {}
            for t_id in sorted(tag_ids):
                row = result_builder.build_row(t_id, preloaded)
                if row is not None:
                    row_by_input_id[t_id] = row

            result: dict[str, TagSearchRow] = {}
            for keyword, ids in tag_ids_by_keyword.items():
                for tag_id in sorted(ids):
                    row = row_by_input_id.get(tag_id)
                    if row is not None:
                        result[keyword] = row
                        break

            return result

    def get_all_tag_ids(self) -> list[int]:
        with self.session_factory() as session:
            return [tag.tag_id for tag in session.query(Tag).all()]

    def get_tag_format_ids(self) -> list[int]:
        with self.session_factory() as session:
            tag_ids = session.query(TagFormat.format_id).distinct().all()
            return [tag_id[0] for tag_id in tag_ids]

    def get_tag_formats(self) -> list[str]:
        with self.session_factory() as session:
            formats = session.query(TagFormat.format_name).distinct().all()
            return sorted([format[0] for format in formats])

    def get_format_map(self) -> dict[int, str]:
        with self.session_factory() as session:
            rows = session.query(TagFormat.format_id, TagFormat.format_name).all()
            return {row[0]: row[1] for row in rows}

    def get_tag_languages(self) -> list[str]:
        with self.session_factory() as session:
            languages = session.query(TagTranslation.language).distinct().all()
            return sorted([lang[0] for lang in languages])

    def get_tag_types(self, format_id: int) -> list[str]:
        with self.session_factory() as session:
            rows = (
                session.query(TagTypeName.type_name)
                .join(TagTypeFormatMapping, TagTypeName.type_name_id == TagTypeFormatMapping.type_name_id)
                .filter(TagTypeFormatMapping.format_id == format_id)
                .all()
            )
        return [row[0] for row in rows]

    def get_unknown_type_tag_ids(self, format_id: int) -> list[int]:
        """Get all tag_ids with type_name="unknown" for the specified format.

        Args:
            format_id: Format ID to filter tags

        Returns:
            list[int]: List of tag_ids with unknown type
        """
        with self.session_factory() as session:
            # Get type_name_id for "unknown"
            unknown_type = (
                session.query(TagTypeName).filter(TagTypeName.type_name == "unknown").one_or_none()
            )
            if not unknown_type:
                return []

            # Get type_id for this format
            mapping = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_name_id == unknown_type.type_name_id,
                )
                .one_or_none()
            )
            if not mapping:
                return []

            # Get all tag_ids with this type_id in this format
            tag_statuses = (
                session.query(TagStatus.tag_id)
                .filter(TagStatus.format_id == format_id, TagStatus.type_id == mapping.type_id)
                .all()
            )

            return [status[0] for status in tag_statuses]

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
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
        with self.session_factory() as session:
            return [type_obj.type_name for type_obj in session.query(TagTypeName).all()]


class TagRepository:
    """Write-only tag repository."""

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        reader: "MergedTagReader | None" = None,
    ):
        self.logger = getLogger(__name__)
        if session_factory is not None:
            self.session_factory = session_factory
        else:
            from genai_tag_db_tools.db.runtime import get_session_factory

            self.session_factory = get_session_factory()
        self._reader = reader

    def create_tag(self, source_tag: str, tag: str) -> int:
        missing_fields: list[str] = []
        if not tag:
            missing_fields.append("tag")
        if not source_tag:
            missing_fields.append("source_tag")

        if missing_fields:
            msg = ErrorMessages.MISSING_REQUIRED_FIELDS.format(fields=", ".join(missing_fields))
            self.logger.error(msg)
            raise ValueError(msg)

        if not self._reader:
            raise ValueError("MergedTagReader not injected")

        existing_id = self._reader.get_tag_id_by_name(tag, partial=False)
        if existing_id is not None:
            return existing_id

        new_tag_data = {"source_tag": source_tag, "tag": tag}
        df = pl.DataFrame(new_tag_data)
        self.bulk_insert_tags(df)

        tag_id = self._reader.get_tag_id_by_name(tag, partial=False)
        if tag_id is None:
            msg = ErrorMessages.TAG_ID_NOT_FOUND_AFTER_INSERT
            self.logger.error(msg)
            raise ValueError(msg)
        return tag_id

    def update_tag(self, tag_id: int, *, source_tag: str | None = None, tag: str | None = None) -> None:
        with self.session_factory() as session:
            tag_obj = session.get(Tag, tag_id)
            if not tag_obj:
                raise ValueError(f"Tag ID {tag_id} does not exist")
            if source_tag is not None:
                tag_obj.source_tag = source_tag
            if tag is not None:
                tag_obj.tag = tag
            session.commit()

    def delete_tag(self, tag_id: int) -> None:
        with self.session_factory() as session:
            tag_obj = session.get(Tag, tag_id)
            if not tag_obj:
                msg = ErrorMessages.INVALID_TAG_ID_DELETION_ATTEMPT.format(tag_id=tag_id)
                self.logger.error(msg)
                raise ValueError(msg)
            session.delete(tag_obj)
            session.commit()

    def bulk_insert_tags(self, df: pl.DataFrame) -> None:
        required_cols = {"source_tag", "tag"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            raise ValueError(f"DataFrame missing required columns: {missing}")

        unique_tag_list = df["tag"].unique().to_list()
        existing_tag_map = self._fetch_existing_tags_as_map(unique_tag_list)

        new_df = df.filter(~pl.col("tag").is_in(list(existing_tag_map.keys())))
        new_df = new_df.unique(subset=["tag"], keep="first")
        if new_df.is_empty():
            return

        records = new_df.select(["source_tag", "tag"]).to_dicts()
        with self.session_factory() as session:
            try:
                session.bulk_insert_mappings(Tag.__mapper__, records)  # type: ignore[arg-type]
                session.commit()
            except IntegrityError as e:
                session.rollback()
                msg = ErrorMessages.DB_OPERATION_FAILED.format(error_msg=str(e))
                raise ValueError(msg) from e

    def create_tag_with_id(self, tag_id: int, source_tag: str, tag: str) -> int:
        if not tag or not source_tag:
            msg = ErrorMessages.MISSING_REQUIRED_FIELDS.format(fields="source_tag, tag")
            self.logger.error(msg)
            raise ValueError(msg)

        with self.session_factory() as session:
            existing_by_id = session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()
            if existing_by_id:
                if existing_by_id.tag != tag:
                    raise ValueError(f"tag_id={tag_id} is already used by '{existing_by_id.tag}'")
                return existing_by_id.tag_id

            existing_by_tag = session.query(Tag).filter(Tag.tag == tag).one_or_none()
            if existing_by_tag:
                if existing_by_tag.tag_id != tag_id:
                    raise ValueError(f"tag='{tag}' already exists with tag_id={existing_by_tag.tag_id}")
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
        if not self._reader:
            raise ValueError("MergedTagReader not injected")

        existing = self._reader.get_tag_by_id(tag_id)
        if existing:
            return existing.tag_id
        return self.create_tag_with_id(tag_id, source_tag, tag)

    def _fetch_existing_tags_as_map(self, tag_list: list[str]) -> dict[str, int]:
        with self.session_factory() as session:
            existing_tags = session.query(Tag.tag, Tag.tag_id).filter(Tag.tag.in_(tag_list)).all()
            return {row[0]: row[1] for row in existing_tags}

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
        """タグステータスを更新または新規作成する。

        Args:
            tag_id: 対象タグID。
            format_id: フォーマットID。
            alias: エイリアスかどうか。
            preferred_tag_id: 優先タグID（alias=Falseの場合はtag_idと一致必須）。
            type_id: タイプID（オプション、Noneなら既存値または0を使用）。
            deprecated: 非推奨フラグ。
            deprecated_at: 非推奨になった日時。
            source_created_at: ソース作成日時。
            updated_at: 更新日時。

        Raises:
            ValueError: バリデーションエラーまたはDB操作エラー。
        """
        self._validate_tag_status_params(alias, preferred_tag_id, tag_id)

        with self.session_factory() as session:
            if type_id is not None:
                self._validate_type_mapping(session, format_id, type_id)

            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )

            effective_type_id = (
                type_id if type_id is not None else (status_obj.type_id if status_obj else 0)
            )

            optional_fields = {
                "deprecated": deprecated,
                "deprecated_at": deprecated_at,
                "source_created_at": source_created_at,
                "updated_at": updated_at,
            }

            if status_obj:
                self._apply_status_update(
                    session, status_obj, effective_type_id, alias, preferred_tag_id, optional_fields
                )
            else:
                self._create_new_status(
                    session, tag_id, format_id, effective_type_id, alias,
                    preferred_tag_id, optional_fields
                )

    @staticmethod
    def _validate_tag_status_params(alias: bool, preferred_tag_id: int, tag_id: int) -> None:
        """タグステータスのパラメータバリデーションを実行する。

        Args:
            alias: エイリアスフラグ。
            preferred_tag_id: 優先タグID。
            tag_id: 対象タグID。

        Raises:
            ValueError: alias=Falseでpreferred_tag_idがtag_idと一致しない場合。
        """
        if not alias and preferred_tag_id != tag_id:
            msg = ErrorMessages.DB_OPERATION_FAILED.format(
                error_msg="preferred_tag_id must match tag_id when alias is False",
            )
            raise ValueError(msg)

    @staticmethod
    def _validate_type_mapping(session: "Session", format_id: int, type_id: int) -> None:
        """type_idとformat_idのマッピングが存在するか検証する。

        Args:
            session: SQLAlchemyセッション。
            format_id: フォーマットID。
            type_id: タイプID。

        Raises:
            ValueError: マッピングが存在しない場合。
        """
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
                error_msg=f"format_id={format_id}, type_id={type_id} not found in mapping"
            )
            raise ValueError(msg)

    @staticmethod
    def _apply_status_update(
        session: "Session",
        status_obj: TagStatus,
        effective_type_id: int,
        alias: bool,
        preferred_tag_id: int,
        optional_fields: dict[str, Any],
    ) -> None:
        """既存のTagStatusレコードを更新する。

        Args:
            session: SQLAlchemyセッション。
            status_obj: 更新対象のTagStatusオブジェクト。
            effective_type_id: 適用するタイプID。
            alias: エイリアスフラグ。
            preferred_tag_id: 優先タグID。
            optional_fields: オプションフィールド（deprecated, deprecated_at等）。
        """
        status_obj.type_id = effective_type_id
        status_obj.alias = alias
        status_obj.preferred_tag_id = preferred_tag_id
        for field_name, value in optional_fields.items():
            if value is not None:
                setattr(status_obj, field_name, value)
        session.commit()

    @staticmethod
    def _create_new_status(
        session: "Session",
        tag_id: int,
        format_id: int,
        effective_type_id: int,
        alias: bool,
        preferred_tag_id: int,
        optional_fields: dict[str, Any],
    ) -> None:
        """新規TagStatusレコードを作成する。

        Args:
            session: SQLAlchemyセッション。
            tag_id: タグID。
            format_id: フォーマットID。
            effective_type_id: タイプID。
            alias: エイリアスフラグ。
            preferred_tag_id: 優先タグID。
            optional_fields: オプションフィールド。

        Raises:
            ValueError: IntegrityErrorが発生した場合。
        """
        try:
            status_obj = TagStatus(
                tag_id=tag_id,
                format_id=format_id,
                type_id=effective_type_id,
                alias=alias,
                preferred_tag_id=preferred_tag_id,
                deprecated=optional_fields.get("deprecated", False) or False,
                deprecated_at=optional_fields.get("deprecated_at"),
                source_created_at=optional_fields.get("source_created_at"),
            )
            session.add(status_obj)
            session.commit()
        except IntegrityError as e:
            session.rollback()
            msg = ErrorMessages.DB_OPERATION_FAILED.format(error_msg=str(e))
            raise ValueError(msg) from e

    def delete_tag_status(self, tag_id: int, format_id: int) -> None:
        with self.session_factory() as session:
            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )
            if status_obj:
                session.delete(status_obj)
                session.commit()

    def update_usage_count(
        self,
        tag_id: int,
        format_id: int,
        count: int,
        *,
        observed_at: datetime | None = None,
    ) -> None:
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

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        with self.session_factory() as session:
            tag = session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()
            if not tag:
                raise ValueError(f"Tag ID not found: {tag_id}")

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
                raise ValueError(f"DB operation failed: {e}") from e

    def create_format_if_not_exists(
        self, format_name: str, description: str | None = None, reader: "MergedTagReader | None" = None
    ) -> int:
        """Create a TagFormat if it doesn't exist, return format_id.

        Args:
            format_name: Name of the format (e.g., "Lorairo", "danbooru")
            description: Optional description
            reader: Optional MergedTagReader to enable user DB format_id reservation (1000+)

        Returns:
            format_id of the existing or newly created format

        Note:
            When reader is provided, user DB uses format_id >= 1000 to avoid collision
            with base DB (which uses 1-999). This ensures environment-independent behavior.
        """
        from genai_tag_db_tools.db.schema import TagFormat

        with self.session_factory() as session:
            # Check if format already exists
            format_obj = session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
            if format_obj:
                return format_obj.format_id

            # Determine next format_id for user DB
            next_format_id = None
            if reader is not None:
                # User DB uses 1000+ range to avoid collision with base DB (1-999)
                # Query existing formats in user DB to find next available ID
                existing_formats = session.query(TagFormat.format_id).all()
                if existing_formats:
                    existing_format_ids = [f.format_id for f in existing_formats]
                    next_format_id = max(existing_format_ids) + 1
                else:
                    # First user format starts at 1000
                    next_format_id = USER_DB_FORMAT_ID_OFFSET
                self.logger.info(
                    f"Allocating format_id={next_format_id} for '{format_name}' in user DB (1000+ range)"
                )

            # Create new format
            new_format = TagFormat(
                format_id=next_format_id,  # None uses auto-increment, explicit value prevents collision
                format_name=format_name,
                description=description,
            )
            session.add(new_format)
            session.commit()
            session.refresh(new_format)
            self.logger.info(f"Created new TagFormat: {format_name} (ID: {new_format.format_id})")
            return new_format.format_id

    def create_type_name_if_not_exists(self, type_name: str, description: str | None = None) -> int:
        """Create a TagTypeName if it doesn't exist, return type_name_id.

        Args:
            type_name: Name of the type (e.g., "unknown", "character")
            description: Optional description

        Returns:
            type_name_id of the existing or newly created type name
        """
        from genai_tag_db_tools.db.schema import TagTypeName

        with self.session_factory() as session:
            # Check if type name already exists
            type_obj = session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            if type_obj:
                return type_obj.type_name_id

            # Create new type name
            new_type = TagTypeName(type_name=type_name, description=description)
            session.add(new_type)
            session.commit()
            session.refresh(new_type)
            self.logger.info(f"Created new TagTypeName: {type_name} (ID: {new_type.type_name_id})")
            return new_type.type_name_id

    def create_type_format_mapping_if_not_exists(
        self, format_id: int, type_id: int, type_name_id: int, description: str | None = None
    ) -> None:
        """Create a TagTypeFormatMapping if it doesn't exist.

        Args:
            format_id: Format ID
            type_id: Type ID (within the format)
            type_name_id: Type name ID (references TagTypeName)
            description: Optional description
        """
        from genai_tag_db_tools.db.schema import TagTypeFormatMapping

        with self.session_factory() as session:
            # Check if mapping already exists
            mapping = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id, TagTypeFormatMapping.type_id == type_id
                )
                .one_or_none()
            )
            if mapping:
                return

            # Create new mapping
            new_mapping = TagTypeFormatMapping(
                format_id=format_id, type_id=type_id, type_name_id=type_name_id, description=description
            )
            session.add(new_mapping)
            session.commit()
            self.logger.info(
                f"Created new TagTypeFormatMapping: format_id={format_id}, type_id={type_id}, type_name_id={type_name_id}"
            )

    def get_next_type_id(self, format_id: int) -> int:
        """Get the next available type_id for a given format.

        This method queries the existing TagTypeFormatMapping entries for the specified
        format_id and returns max(type_id) + 1. If no mappings exist for the format,
        it returns 0.

        Args:
            format_id: Format ID to get the next type_id for

        Returns:
            Next available type_id (0 if no mappings exist for this format)

        Example:
            >>> repo = TagRepository()
            >>> next_id = repo.get_next_type_id(format_id=1000)
            >>> # Returns 0 if no type mappings exist for format 1000
            >>> # Returns max(type_id) + 1 if mappings exist
        """
        from sqlalchemy import func

        from genai_tag_db_tools.db.schema import TagTypeFormatMapping

        with self.session_factory() as session:
            max_type_id = (
                session.query(func.max(TagTypeFormatMapping.type_id))
                .filter(TagTypeFormatMapping.format_id == format_id)
                .scalar()
            )

            if max_type_id is None:
                return 0

            return max_type_id + 1

    def _resolve_type_id_for_format(
        self,
        session: "Session",
        type_name: str,
        type_name_id: int,
        format_id: int,
        cache: dict[str, int],
    ) -> int:
        """format_id に対応する type_id を解決する。既存マッピングがなければ新規作成する。

        Args:
            session: 現在のSQLAlchemyセッション。
            type_name: タイプ名文字列。
            type_name_id: タイプ名のDB ID。
            format_id: フォーマットID。
            cache: type_name → type_id のキャッシュ辞書（直接更新される）。

        Returns:
            解決された type_id。
        """
        if type_name in cache:
            return cache[type_name]

        from genai_tag_db_tools.db.schema import TagTypeFormatMapping

        mapping = (
            session.query(TagTypeFormatMapping)
            .filter(
                TagTypeFormatMapping.format_id == format_id,
                TagTypeFormatMapping.type_name_id == type_name_id,
            )
            .first()
        )

        if mapping:
            cache[type_name] = mapping.type_id
        else:
            next_type_id = self.get_next_type_id(format_id)
            self.create_type_format_mapping_if_not_exists(
                format_id=format_id,
                type_id=next_type_id,
                type_name_id=type_name_id,
            )
            cache[type_name] = next_type_id
            self.logger.info(
                f"Created new type mapping: format_id={format_id}, "
                f"type_id={next_type_id}, type_name={type_name}"
            )

        return cache[type_name]

    def update_tags_type_batch(
        self,
        tag_updates: list,  # list[TagTypeUpdate] - avoid circular import
        format_id: int,
    ) -> None:
        """Update type_id for multiple tags in a single transaction.

        This method processes a batch of tag type updates, automatically creating
        type_name and TagTypeFormatMapping entries as needed. All updates are
        performed within a single transaction for atomicity.

        Args:
            tag_updates: List of TagTypeUpdate objects containing tag_id and type_name
            format_id: Format ID for the tags being updated

        Raises:
            ValueError: If format_id or any tag_id is invalid
            Exception: If transaction fails and needs to be rolled back

        Example:
            >>> from genai_tag_db_tools.models import TagTypeUpdate
            >>> repo = TagRepository()
            >>> updates = [
            ...     TagTypeUpdate(tag_id=123, type_name="character"),
            ...     TagTypeUpdate(tag_id=456, type_name="general"),
            ... ]
            >>> repo.update_tags_type_batch(updates, format_id=1000)
        """
        if not tag_updates:
            return

        with self.session_factory() as session:
            try:
                # Cache for type_name -> type_id mapping (format-specific)
                type_name_to_type_id: dict[str, int] = {}

                for update in tag_updates:
                    # Step 1: Get or create type_name_id
                    type_name_id = self.create_type_name_if_not_exists(update.type_name)

                    # Step 2: Get or create format-specific type_id
                    type_id = self._resolve_type_id_for_format(
                        session, update.type_name, type_name_id, format_id, type_name_to_type_id
                    )

                    # Step 3: Update tag status with new type_id
                    self.update_tag_status(
                        tag_id=update.tag_id,
                        format_id=format_id,
                        alias=False,
                        preferred_tag_id=update.tag_id,
                        type_id=type_id,
                    )

                session.commit()
                self.logger.info(
                    f"Updated {len(tag_updates)} tags with new type assignments for format_id={format_id}"
                )

            except Exception as e:
                session.rollback()
                self.logger.error(f"Failed to update tag types in batch: {e}", exc_info=True)
                raise


class MergedTagReader:
    """Read-only view merging base/user repositories."""

    def __init__(
        self,
        base_repo: TagReader | list[TagReader],
        user_repo: TagReader | None = None,
    ):
        self.logger = getLogger(__name__)
        if isinstance(base_repo, list):
            if not base_repo:
                raise ValueError("base_repo must not be empty")
            self.base_repos = base_repo
        else:
            self.base_repos = [base_repo]
        self.base_repo = self.base_repos[0]
        self.user_repo = user_repo

    def _has_user(self) -> bool:
        return self.user_repo is not None

    def _iter_base_repos(self) -> list[TagReader]:
        return list(self.base_repos)

    def _iter_base_repos_low_to_high(self) -> list[TagReader]:
        return list(reversed(self.base_repos))

    def _iter_repos(self) -> list[TagReader]:
        repos: list[TagReader] = []
        if self.user_repo is not None:
            repos.append(self.user_repo)
        repos.extend(self.base_repos)
        return repos

    # ------------------------------------------------------------------
    # パターンヘルパー (内部利用)
    # ------------------------------------------------------------------

    def _first_found(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """ユーザーDBを優先し、最初に見つかった非None結果を返す。

        user_repo → base_repos (優先度高→低) の順に呼び出し、
        最初に None でない値を返したリポジトリの結果をそのまま返す。

        Args:
            method_name: TagReader上のメソッド名。
            *args: メソッドへの位置引数。
            **kwargs: メソッドへのキーワード引数。

        Returns:
            最初に見つかった非None結果。見つからなければNone。
        """
        if self._has_user():
            assert self.user_repo is not None
            result = getattr(self.user_repo, method_name)(*args, **kwargs)
            if result is not None:
                return result
        for repo in self._iter_base_repos():
            result = getattr(repo, method_name)(*args, **kwargs)
            if result is not None:
                return result
        return None

    def _merge_by_key(
        self,
        method_name: str,
        key_fn: Callable[[Any], Any] | None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """全リポジトリから収集し、キーで重複排除してマージする。

        base_repos (低優先度→高優先度) → user_repo の順に呼び出す。
        同一キーのエントリは後勝ちで上書きされるため、user_repoが最優先となる。

        key_fn が None の場合、メソッドの戻り値を dict とみなし
        dict.update() でマージする。
        key_fn が指定された場合、メソッドの戻り値を list とみなし
        各要素に key_fn を適用して dict にマージし、values() を返す。

        Args:
            method_name: TagReader上のメソッド名。
            key_fn: リスト要素からキーを抽出する関数。Noneならdict戻り値として処理。
            *args: メソッドへの位置引数。
            **kwargs: メソッドへのキーワード引数。

        Returns:
            マージ済みリスト (key_fn指定時) またはマージ済みdict (key_fn=None時)。
        """
        merged: dict[Any, Any] = {}
        for repo in self._iter_base_repos_low_to_high():
            result = getattr(repo, method_name)(*args, **kwargs)
            if key_fn is None:
                merged.update(result)
            else:
                for item in result:
                    merged[key_fn(item)] = item
        if self._has_user():
            assert self.user_repo is not None
            result = getattr(self.user_repo, method_name)(*args, **kwargs)
            if key_fn is None:
                merged.update(result)
            else:
                for item in result:
                    merged[key_fn(item)] = item
        if key_fn is None:
            return merged
        return list(merged.values())

    def _accumulate_unique(
        self,
        method_name: str,
        key_fn: Callable[[Any], tuple[Any, ...]],
        *args: Any,
        **kwargs: Any,
    ) -> list[Any]:
        """全リポジトリから収集し、キータプルで重複排除する。

        base_repos (低優先度→高優先度) → user_repo の順に収集し、
        key_fn で生成したタプルを既出管理に使い、先着順で保持する。

        Args:
            method_name: TagReader上のメソッド名。
            key_fn: 各要素から重複判定用タプルを生成する関数。
            *args: メソッドへの位置引数。
            **kwargs: メソッドへのキーワード引数。

        Returns:
            重複排除済みのリスト。
        """
        items: list[Any] = []
        for repo in self._iter_base_repos_low_to_high():
            items += getattr(repo, method_name)(*args, **kwargs)
        if self._has_user():
            assert self.user_repo is not None
            items += getattr(self.user_repo, method_name)(*args, **kwargs)

        seen: set[tuple[Any, ...]] = set()
        unique: list[Any] = []
        for item in items:
            key = key_fn(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    # ------------------------------------------------------------------
    # Pattern A: _first_found (user優先、最初の非None結果)
    # ------------------------------------------------------------------

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        return self._first_found("get_tag_id_by_name", keyword, partial=partial)

    def get_tag_by_id(self, tag_id: int) -> Tag | None:
        return self._first_found("get_tag_by_id", tag_id)

    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        return self._first_found("get_tag_status", tag_id, format_id)

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        return self._first_found("get_usage_count", tag_id, format_id)

    def get_format_name(self, format_id: int) -> str | None:
        return self._first_found("get_format_name", format_id)

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        return self._first_found("get_type_name_by_format_type_id", format_id, type_id)

    def get_type_id(self, type_name: str) -> int | None:
        return self._first_found("get_type_id", type_name)

    def get_metadata_value(self, key: str) -> str | None:
        return self._first_found("get_metadata_value", key)

    def get_format_id(self, format_name: str) -> int:
        result = self._first_found("get_format_id", format_name)
        if result:
            return result
        raise ValueError(f"format_name not found: {format_name}")

    # ------------------------------------------------------------------
    # Pattern B: _merge_by_key (全リポから収集、キーで重複排除マージ)
    # ------------------------------------------------------------------

    def list_tags(self) -> list[Tag]:
        return self._merge_by_key("list_tags", lambda t: t.tag_id)

    def list_tag_statuses(self, tag_id: int | None = None) -> list[TagStatus]:
        return self._merge_by_key(
            "list_tag_statuses",
            lambda s: (s.tag_id, s.format_id),
            tag_id=tag_id,
        )

    def list_usage_counts(
        self, tag_id: int | None = None, format_id: int | None = None
    ) -> list[TagUsageCounts]:
        return self._merge_by_key(
            "list_usage_counts",
            lambda r: (r.tag_id, r.format_id),
            tag_id=tag_id,
            format_id=format_id,
        )

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
    ) -> list[TagSearchRow]:
        return self._merge_by_key(
            "search_tags",
            lambda row: row["tag_id"],
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

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, TagSearchRow]:
        return self._merge_by_key(
            "search_tags_bulk",
            None,
            keywords,
            format_name=format_name,
            resolve_preferred=resolve_preferred,
        )

    def get_format_map(self) -> dict[int, str]:
        return self._merge_by_key("get_format_map", None)

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
        return self._merge_by_key("get_type_mapping_map", None)

    # ------------------------------------------------------------------
    # Pattern C: _accumulate_unique (全リポから収集、タプルキーで重複排除)
    # ------------------------------------------------------------------

    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        return self._accumulate_unique(
            "get_translations",
            lambda tr: (tr.language, tr.translation),
            tag_id,
        )

    def list_translations(self) -> list[TagTranslation]:
        return self._accumulate_unique(
            "list_translations",
            lambda tr: (tr.tag_id, tr.language, tr.translation),
        )

    # ------------------------------------------------------------------
    # Pattern D: Union/aggregate (固有ロジックのため明示的に実装)
    # ------------------------------------------------------------------

    def get_max_tag_id(self) -> int:
        return max(
            (repo.get_max_tag_id() for repo in self._iter_repos()),
            default=0,
        )

    def search_tag_ids(self, keyword: str, partial: bool = False) -> list[int]:
        tag_ids: set[int] = set()
        for repo in self._iter_repos():
            tag_ids |= set(repo.search_tag_ids(keyword, partial=partial))
        return list(tag_ids)

    def get_all_tag_ids(self) -> list[int]:
        tag_ids: set[int] = set()
        for repo in self._iter_repos():
            tag_ids |= set(repo.get_all_tag_ids())
        return list(tag_ids)

    def get_unknown_type_tag_ids(self, format_id: int) -> list[int]:
        """指定フォーマットで type_name="unknown" の全tag_idを取得する。

        Args:
            format_id: フィルタ対象のフォーマットID。

        Returns:
            list[int]: unknownタイプのtag_idリスト。
        """
        tag_ids: set[int] = set()
        for repo in self._iter_repos():
            tag_ids |= set(repo.get_unknown_type_tag_ids(format_id))
        return list(tag_ids)

    # ------------------------------------------------------------------
    # Pattern E: Set union (簡易集約)
    # ------------------------------------------------------------------

    def get_tag_format_ids(self) -> list[int]:
        format_ids: set[int] = set()
        for repo in self._iter_repos():
            format_ids |= set(repo.get_tag_format_ids())
        return list(format_ids)

    def get_tag_formats(self) -> list[str]:
        formats: set[str] = set()
        for repo in self._iter_repos():
            formats |= set(repo.get_tag_formats())
        return sorted(formats)

    def get_tag_languages(self) -> list[str]:
        languages: set[str] = set()
        for repo in self._iter_repos():
            languages |= set(repo.get_tag_languages())
        return sorted(languages)

    def get_tag_types(self, format_id: int) -> list[str]:
        types: set[str] = set()
        for repo in self._iter_repos():
            types |= set(repo.get_tag_types(format_id))
        return list(types)

    def get_all_types(self) -> list[str]:
        types: set[str] = set()
        for repo in self._iter_repos():
            types |= set(repo.get_all_types())
        return list(types)

    # ------------------------------------------------------------------
    # その他
    # ------------------------------------------------------------------

    def get_database_version(self) -> str | None:
        return self.get_metadata_value("version")


def get_default_reader() -> MergedTagReader:
    from genai_tag_db_tools.db.runtime import (
        get_base_session_factories,
        get_user_session_factory_optional,
    )

    user_factory = get_user_session_factory_optional()
    user_repo = TagReader(session_factory=user_factory) if user_factory else None

    base_factories = get_base_session_factories()
    if not base_factories:
        if user_repo:
            return MergedTagReader(base_repo=user_repo, user_repo=None)
        raise ValueError("No database available")

    if len(base_factories) == 1:
        base_repo = TagReader(session_factory=base_factories[0])
        return MergedTagReader(base_repo=base_repo, user_repo=user_repo)

    base_repos = [TagReader(session_factory=f) for f in base_factories]
    return MergedTagReader(base_repo=base_repos, user_repo=user_repo)


def get_default_repository() -> TagRepository:
    from genai_tag_db_tools.db.runtime import get_user_session_factory_optional

    user_factory = get_user_session_factory_optional()
    if not user_factory:
        raise ValueError("User database not available for write operations")

    return TagRepository(session_factory=user_factory, reader=get_default_reader())
