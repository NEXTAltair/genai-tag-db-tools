from collections.abc import Callable
from datetime import datetime
from logging import getLogger

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
        if not alias and preferred_tag_id != tag_id:
            msg = ErrorMessages.DB_OPERATION_FAILED.format(
                error_msg="preferred_tag_id must match tag_id when alias is False",
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
                        error_msg=(f"format_id={format_id}, type_id={type_id} not found in mapping")
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

    def create_format_if_not_exists(self, format_name: str, description: str | None = None) -> int:
        """Create a TagFormat if it doesn't exist, return format_id.

        Args:
            format_name: Name of the format (e.g., "Lorairo", "danbooru")
            description: Optional description

        Returns:
            format_id of the existing or newly created format
        """
        from genai_tag_db_tools.db.schema import TagFormat

        with self.session_factory() as session:
            # Check if format already exists
            format_obj = session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
            if format_obj:
                return format_obj.format_id

            # Create new format
            new_format = TagFormat(format_name=format_name, description=description)
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

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        if self._has_user():
            assert self.user_repo is not None
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
            assert self.user_repo is not None
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
            assert self.user_repo is not None
            for tag in self.user_repo.list_tags():
                merged[tag.tag_id] = tag
        return list(merged.values())

    def get_max_tag_id(self) -> int:
        max_id = 0
        for repo in self._iter_repos():
            repo_max = repo.get_max_tag_id()
            if repo_max > max_id:
                max_id = repo_max
        return max_id

    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        if self._has_user():
            assert self.user_repo is not None
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
            assert self.user_repo is not None
            for status in self.user_repo.list_tag_statuses(tag_id=tag_id):
                merged[(status.tag_id, status.format_id)] = status
        return list(merged.values())

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        if self._has_user():
            assert self.user_repo is not None
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
            assert self.user_repo is not None
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

    def list_translations(self) -> list[TagTranslation]:
        translations: list[TagTranslation] = []
        for repo in self._iter_base_repos_low_to_high():
            translations += repo.list_translations()
        if self._has_user():
            translations += self.user_repo.list_translations()

        seen: set[tuple[int, str, str]] = set()
        unique: list[TagTranslation] = []
        for tr in translations:
            key = (tr.tag_id, tr.language, tr.translation)
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
    ) -> list[TagSearchRow]:
        merged: dict[int, TagSearchRow] = {}
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
            )
            for row in user_rows:
                merged[row["tag_id"]] = row
        return list(merged.values())

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, TagSearchRow]:
        merged: dict[str, TagSearchRow] = {}
        for repo in self._iter_base_repos_low_to_high():
            merged.update(
                repo.search_tags_bulk(
                    keywords,
                    format_name=format_name,
                    resolve_preferred=resolve_preferred,
                )
            )
        if self._has_user():
            merged.update(
                self.user_repo.search_tags_bulk(
                    keywords,
                    format_name=format_name,
                    resolve_preferred=resolve_preferred,
                )
            )
        return merged

    def get_all_tag_ids(self) -> list[int]:
        tag_ids: set[int] = set()
        for repo in self._iter_base_repos():
            tag_ids |= set(repo.get_all_tag_ids())
        if self._has_user():
            tag_ids |= set(self.user_repo.get_all_tag_ids())
        return list(tag_ids)

    def get_tag_format_ids(self) -> list[int]:
        format_ids: set[int] = set()
        for repo in self._iter_repos():
            format_ids |= set(repo.get_tag_format_ids())
        return list(format_ids)

    def get_tag_formats(self) -> list[str]:
        formats: set[str] = set()
        for repo in self._iter_base_repos():
            formats |= set(repo.get_tag_formats())
        if self._has_user():
            formats |= set(self.user_repo.get_tag_formats())
        return sorted(formats)

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
        return sorted(languages)

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
        raise ValueError(f"format_name not found: {format_name}")

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

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        if self._has_user():
            name = self.user_repo.get_type_name_by_format_type_id(format_id, type_id)
            if name is not None:
                return name
        for repo in self._iter_base_repos():
            name = repo.get_type_name_by_format_type_id(format_id, type_id)
            if name is not None:
                return name
        return None

    def get_type_id(self, type_name: str) -> int | None:
        if self._has_user():
            type_id = self.user_repo.get_type_id(type_name)
            if type_id is not None:
                return type_id
        for repo in self._iter_base_repos():
            type_id = repo.get_type_id(type_name)
            if type_id is not None:
                return type_id
        return None

    def get_metadata_value(self, key: str) -> str | None:
        if self._has_user():
            value = self.user_repo.get_metadata_value(key)
            if value is not None:
                return value
        for repo in self._iter_base_repos():
            value = repo.get_metadata_value(key)
            if value is not None:
                return value
        return None

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
