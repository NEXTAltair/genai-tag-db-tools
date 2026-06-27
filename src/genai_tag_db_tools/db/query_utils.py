from logging import Logger
from typing import Any, TypedDict

from sqlalchemy import exists, func, not_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import literal_column, or_

from genai_tag_db_tools.db.schema import (
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
)
from genai_tag_db_tools.models import PreloadedData, TagSearchRow


class StatusInfo(TypedDict):
    """Status information for a tag."""

    usage_count: int
    is_alias: bool
    resolved_type_name: str
    resolved_type_id: int | None
    preferred_tag_id: int
    deprecated: bool


def normalize_search_keyword(keyword: str, partial: bool) -> tuple[str, bool]:
    """Normalize a search keyword for SQL LIKE conditions."""
    has_wildcard = "*" in keyword or "%" in keyword or partial
    if "*" in keyword:
        keyword = keyword.replace("*", "%")

    if has_wildcard:
        if not keyword.startswith("%"):
            keyword = "%" + keyword
        if not keyword.endswith("%"):
            keyword = keyword + "%"

    return keyword, has_wildcard


class TagSearchQueryBuilder:
    """Build search tag_id sets based on filter conditions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def initial_tag_ids(
        self,
        keyword: str,
        use_like: bool,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> set[int]:
        # 完全一致 (use_like=False) は大文字小文字を無視して照合する (COLLATE NOCASE)。
        # LIKE は SQLite 既定で ASCII 大文字小文字を無視するため挙動は変えない。
        tag_conditions = or_(
            Tag.tag.like(keyword) if use_like else Tag.tag.collate("NOCASE") == keyword,
            Tag.source_tag.like(keyword) if use_like else Tag.source_tag.collate("NOCASE") == keyword,
        )
        translation_condition = (
            TagTranslation.translation.like(keyword)
            if use_like
            else TagTranslation.translation.collate("NOCASE") == keyword
        )

        tag_query = self.session.query(Tag.tag_id.label("tag_id")).filter(tag_conditions)
        translation_query = self.session.query(TagTranslation.tag_id.label("tag_id")).filter(
            translation_condition
        )

        # tag と translation の一致を UNION で重複排除してから limit/offset を適用する。
        # 各クエリ個別に limit すると、同一タグの多言語 translation 行が窓を食い潰し
        # ユニークな tag_id 数が limit に満たなくなる (重複排除が limit の後になる問題)。
        # ページングを決定的にするため tag_id 昇順で order_by する。
        union_query = tag_query.union(translation_query).order_by(literal_column("tag_id"))
        if offset:
            union_query = union_query.offset(offset)
        if limit is not None:
            union_query = union_query.limit(limit)

        return {row[0] for row in union_query.all()}

    def filtered_tag_ids(
        self,
        keyword: str,
        use_like: bool,
        *,
        format_names: list[str] | None = None,
        type_names: list[str] | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
        deprecated: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[set[int], int]:
        """Return tag ids after applying search filters before limit/offset.

        The returned format id is only set when exactly one concrete format was
        requested; result row construction uses that to expose format-specific
        status fields.
        """
        concrete_format_names = self._normalize_filter_names(format_names)
        format_ids = self._format_ids_for_names(concrete_format_names)
        if concrete_format_names and not format_ids:
            return set(), 0

        concrete_type_names = self._normalize_filter_names(type_names)
        type_name_ids = self._type_name_ids_for_names(concrete_type_names)
        if concrete_type_names and not type_name_ids:
            return set(), 0

        candidate = self._keyword_candidate_query(keyword, use_like).subquery()
        query = self.session.query(candidate.c.tag_id)
        query = self._apply_status_exists_filters(
            query,
            candidate.c.tag_id,
            format_ids=format_ids,
            type_name_ids=type_name_ids,
            alias=alias,
            deprecated=deprecated,
        )
        query = self._apply_usage_exists_filter(
            query,
            candidate.c.tag_id,
            format_ids=format_ids,
            min_usage=min_usage,
            max_usage=max_usage,
        )
        query = self._apply_language_exists_filter(query, candidate.c.tag_id, language)
        query = query.order_by(candidate.c.tag_id)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        format_id = format_ids[0] if len(format_ids) == 1 else 0
        return {row[0] for row in query.all()}, format_id

    def _keyword_candidate_query(self, keyword: str, use_like: bool) -> Any:
        # 完全一致 (use_like=False) は COLLATE NOCASE で大文字小文字を無視する。
        tag_conditions = or_(
            Tag.tag.like(keyword) if use_like else Tag.tag.collate("NOCASE") == keyword,
            Tag.source_tag.like(keyword) if use_like else Tag.source_tag.collate("NOCASE") == keyword,
        )
        translation_condition = (
            TagTranslation.translation.like(keyword)
            if use_like
            else TagTranslation.translation.collate("NOCASE") == keyword
        )

        tag_query = self.session.query(Tag.tag_id.label("tag_id")).filter(tag_conditions)
        translation_query = self.session.query(TagTranslation.tag_id.label("tag_id")).filter(
            translation_condition
        )
        return tag_query.union(translation_query)

    def _format_ids_for_names(self, format_names: list[str] | None) -> list[int]:
        names = self._normalize_filter_names(format_names)
        if not names:
            return []
        rows = self.session.query(TagFormat.format_id).filter(TagFormat.format_name.in_(names)).all()
        return [row[0] for row in rows]

    def _type_name_ids_for_names(self, type_names: list[str] | None) -> list[int]:
        names = self._normalize_filter_names(type_names)
        if not names:
            return []
        rows = self.session.query(TagTypeName.type_name_id).filter(TagTypeName.type_name.in_(names)).all()
        return [row[0] for row in rows]

    def _normalize_filter_names(self, names: list[str] | None) -> list[str]:
        if not names:
            return []
        return [name for name in names if name and name.lower() != "all"]

    def _apply_status_exists_filters(
        self,
        query: Any,
        tag_id_column: Any,
        *,
        format_ids: list[int],
        type_name_ids: list[int],
        alias: bool | None,
        deprecated: bool | None,
    ) -> Any:
        if not format_ids and not type_name_ids and alias is None and deprecated is None:
            return query

        if not format_ids and not type_name_ids:
            if alias is True or deprecated is True:
                status_select = select(TagStatus.tag_id).where(TagStatus.tag_id == tag_id_column)
                if alias is True:
                    status_select = status_select.where(TagStatus.alias == alias)
                if deprecated is True:
                    status_select = status_select.where(TagStatus.deprecated == deprecated)
                query = query.filter(exists(status_select))
            if alias is False:
                alias_select = select(TagStatus.tag_id).where(
                    TagStatus.tag_id == tag_id_column,
                    TagStatus.alias.is_(True),
                )
                query = query.filter(not_(exists(alias_select)))
            if deprecated is False:
                deprecated_select = select(TagStatus.tag_id).where(
                    TagStatus.tag_id == tag_id_column,
                    TagStatus.deprecated.is_(True),
                )
                query = query.filter(not_(exists(deprecated_select)))
            return query

        status_select = select(TagStatus.tag_id).where(TagStatus.tag_id == tag_id_column)
        if type_name_ids:
            status_select = status_select.join(
                TagTypeFormatMapping,
                (TagStatus.format_id == TagTypeFormatMapping.format_id)
                & (TagStatus.type_id == TagTypeFormatMapping.type_id),
            ).where(TagTypeFormatMapping.type_name_id.in_(type_name_ids))
        if format_ids:
            status_select = status_select.where(TagStatus.format_id.in_(format_ids))
        if alias is not None:
            status_select = status_select.where(TagStatus.alias == alias)
        if deprecated is not None:
            status_select = status_select.where(TagStatus.deprecated == deprecated)
        return query.filter(exists(status_select))

    def _apply_usage_exists_filter(
        self,
        query: Any,
        tag_id_column: Any,
        *,
        format_ids: list[int],
        min_usage: int | None,
        max_usage: int | None,
    ) -> Any:
        if min_usage is None and max_usage is None:
            return query

        matching_usage = select(TagUsageCounts.tag_id).where(TagUsageCounts.tag_id == tag_id_column)
        any_usage = select(TagUsageCounts.tag_id).where(TagUsageCounts.tag_id == tag_id_column)
        if format_ids:
            matching_usage = matching_usage.where(TagUsageCounts.format_id.in_(format_ids))
            any_usage = any_usage.where(TagUsageCounts.format_id.in_(format_ids))
        if min_usage is not None:
            matching_usage = matching_usage.where(TagUsageCounts.count >= min_usage)
        if max_usage is not None:
            matching_usage = matching_usage.where(TagUsageCounts.count <= max_usage)

        condition: Any = exists(matching_usage)
        if self._should_include_missing_usage(min_usage, max_usage):
            condition = or_(condition, not_(exists(any_usage)))
        return query.filter(condition)

    def _apply_language_exists_filter(self, query: Any, tag_id_column: Any, language: str | None) -> Any:
        if not language or language.lower() == "all":
            return query
        language_select = select(TagTranslation.tag_id).where(
            TagTranslation.tag_id == tag_id_column,
            TagTranslation.language == language,
        )
        return query.filter(exists(language_select))

    def initial_tag_ids_for_keywords(self, keywords: list[str]) -> dict[str, set[int]]:
        if not keywords:
            return {}

        keyword_set = set(keywords)
        # 大文字小文字を無視して照合するため lower 化したキーで突き合わせる。
        # 同一 lower 値を持つ keyword が複数あっても、それぞれに tag_id を割り当てる。
        keywords_by_lower: dict[str, set[str]] = {}
        for keyword in keyword_set:
            keywords_by_lower.setdefault(keyword.lower(), set()).add(keyword)
        lower_keys = list(keywords_by_lower.keys())

        tag_rows = (
            self.session.query(Tag.tag_id, Tag.tag, Tag.source_tag)
            .filter(
                or_(
                    func.lower(Tag.tag).in_(lower_keys),
                    func.lower(Tag.source_tag).in_(lower_keys),
                )
            )
            .all()
        )
        trans_rows = (
            self.session.query(TagTranslation.tag_id, TagTranslation.translation)
            .filter(func.lower(TagTranslation.translation).in_(lower_keys))
            .all()
        )

        tag_ids_by_keyword: dict[str, set[int]] = {keyword: set() for keyword in keyword_set}
        for tag_id, tag, source_tag in tag_rows:
            for value in (tag, source_tag):
                if value is None:
                    continue
                for keyword in keywords_by_lower.get(value.lower(), ()):
                    tag_ids_by_keyword[keyword].add(tag_id)
        for tag_id, translation in trans_rows:
            if translation is None:
                continue
            for keyword in keywords_by_lower.get(translation.lower(), ()):
                tag_ids_by_keyword[keyword].add(tag_id)

        return {keyword: ids for keyword, ids in tag_ids_by_keyword.items() if ids}

    def apply_format_filter(self, tag_ids: set[int], format_name: str | None) -> tuple[set[int], int]:
        if not format_name or format_name.lower() == "all":
            return tag_ids, 0

        fmt_obj = self.session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
        if not fmt_obj:
            return set(), 0

        format_id = fmt_obj.format_id
        format_tag_ids = {
            row[0]
            for row in self.session.query(TagStatus.tag_id).filter(TagStatus.format_id == format_id).all()
        }
        return tag_ids & format_tag_ids, format_id

    def apply_usage_filter(
        self,
        tag_ids: set[int],
        format_id: int,
        min_usage: int | None,
        max_usage: int | None,
    ) -> set[int]:
        if min_usage is None and max_usage is None:
            return tag_ids

        usage_tag_ids = self._query_usage_tag_ids(format_id, min_usage, max_usage)
        if self._should_include_missing_usage(min_usage, max_usage):
            usage_tag_ids = self._include_missing_usage_tag_ids(tag_ids, format_id, usage_tag_ids)

        return tag_ids & usage_tag_ids

    def _query_usage_tag_ids(
        self,
        format_id: int,
        min_usage: int | None,
        max_usage: int | None,
    ) -> set[int]:
        usage_query = self.session.query(TagUsageCounts.tag_id)
        if format_id:
            usage_query = usage_query.filter(TagUsageCounts.format_id == format_id)
        if min_usage is not None:
            usage_query = usage_query.filter(TagUsageCounts.count >= min_usage)
        if max_usage is not None:
            usage_query = usage_query.filter(TagUsageCounts.count <= max_usage)
        return {row[0] for row in usage_query.all()}

    def _should_include_missing_usage(
        self,
        min_usage: int | None,
        max_usage: int | None,
    ) -> bool:
        return (min_usage is None or min_usage <= 0) and (max_usage is None or max_usage >= 0)

    def _include_missing_usage_tag_ids(
        self,
        tag_ids: set[int],
        format_id: int,
        usage_tag_ids: set[int],
    ) -> set[int]:
        usage_all_query = self.session.query(TagUsageCounts.tag_id)
        if format_id:
            usage_all_query = usage_all_query.filter(TagUsageCounts.format_id == format_id)
        usage_all_tag_ids = {row[0] for row in usage_all_query.all()}
        return usage_tag_ids | (tag_ids - usage_all_tag_ids)

    def apply_type_filter(self, tag_ids: set[int], format_id: int, type_name: str | None) -> set[int]:
        if not type_name or type_name.lower() == "all":
            return tag_ids

        type_obj = self.session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
        if not type_obj:
            return set()

        type_query = self.session.query(TagStatus.tag_id).join(
            TagTypeFormatMapping,
            (TagStatus.format_id == TagTypeFormatMapping.format_id)
            & (TagStatus.type_id == TagTypeFormatMapping.type_id),
        )
        type_query = type_query.filter(TagTypeFormatMapping.type_name_id == type_obj.type_name_id)
        if format_id:
            type_query = type_query.filter(TagStatus.format_id == format_id)
        type_tag_ids = {row[0] for row in type_query.all()}
        return tag_ids & type_tag_ids

    def apply_alias_filter(self, tag_ids: set[int], format_id: int, alias: bool | None) -> set[int]:
        if alias is None:
            return tag_ids

        alias_query = self.session.query(TagStatus.tag_id).filter(TagStatus.alias == alias)
        if format_id:
            alias_query = alias_query.filter(TagStatus.format_id == format_id)
        alias_tag_ids = {row[0] for row in alias_query.all()}
        return tag_ids & alias_tag_ids

    def apply_language_filter(self, tag_ids: set[int], language: str | None) -> set[int]:
        if not language or language.lower() == "all":
            return tag_ids

        lang_query = self.session.query(TagTranslation.tag_id).filter(TagTranslation.language == language)
        lang_tag_ids = {row[0] for row in lang_query.all()}
        return tag_ids & lang_tag_ids


class TagSearchPreloader:
    """Preload related tag data to avoid N+1 queries during search."""

    SQLITE_IN_LIMIT = 900

    def __init__(self, session: Session) -> None:
        self.session = session

    def _query_in_chunks(self, query: Any, column: Any, ids: set[int]) -> list:
        """SQLite の IN 句変数上限を避けるため、ids をチャンク分割してクエリを実行する。"""
        if not ids:
            return []

        id_list = sorted(ids)
        rows: list = []
        for i in range(0, len(id_list), self.SQLITE_IN_LIMIT):
            chunk = id_list[i : i + self.SQLITE_IN_LIMIT]
            rows.extend(query.filter(column.in_(chunk)).all())
        return rows

    def load(self, tag_ids: set[int]) -> PreloadedData:
        if not tag_ids:
            return PreloadedData(
                format_name_by_id={},
                type_name_by_key={},
                usage_by_key={},
                tags_by_id={},
                trans_by_tag_id={},
                status_by_tag_format={},
                statuses_by_tag_id={},
            )

        initial_status_rows = self._query_in_chunks(
            self.session.query(TagStatus), TagStatus.tag_id, tag_ids
        )
        preferred_ids = {
            row.preferred_tag_id for row in initial_status_rows if row.preferred_tag_id is not None
        }
        status_tag_ids = set(tag_ids) | preferred_ids
        status_rows = self._query_in_chunks(self.session.query(TagStatus), TagStatus.tag_id, status_tag_ids)
        format_ids = {row.format_id for row in status_rows}
        format_name_by_id = {
            fmt.format_id: fmt.format_name
            for fmt in self._query_in_chunks(self.session.query(TagFormat), TagFormat.format_id, format_ids)
        }
        type_name_by_key = {
            (mapping.format_id, mapping.type_id): (mapping.type_name.type_name if mapping.type_name else "")
            for mapping in self._query_in_chunks(
                self.session.query(TagTypeFormatMapping),
                TagTypeFormatMapping.format_id,
                format_ids,
            )
        }
        usage_by_key = {
            (usage.tag_id, usage.format_id): usage.count
            for usage in self._query_in_chunks(
                self.session.query(TagUsageCounts), TagUsageCounts.tag_id, status_tag_ids
            )
        }
        tags_by_id = {
            t.tag_id: t for t in self._query_in_chunks(self.session.query(Tag), Tag.tag_id, status_tag_ids)
        }
        all_translations = self._query_in_chunks(
            self.session.query(TagTranslation), TagTranslation.tag_id, status_tag_ids
        )
        trans_by_tag_id: dict[int, list[TagTranslation]] = {}
        for tr in all_translations:
            trans_by_tag_id.setdefault(tr.tag_id, []).append(tr)

        status_by_tag_format: dict[tuple[int, int], TagStatus] = {}
        statuses_by_tag_id: dict[int, list[TagStatus]] = {}
        for status in status_rows:
            status_by_tag_format[(status.tag_id, status.format_id)] = status
            statuses_by_tag_id.setdefault(status.tag_id, []).append(status)

        return PreloadedData(
            format_name_by_id=format_name_by_id,
            type_name_by_key=type_name_by_key,
            usage_by_key=usage_by_key,
            tags_by_id=tags_by_id,
            trans_by_tag_id=trans_by_tag_id,
            status_by_tag_format=status_by_tag_format,
            statuses_by_tag_id=statuses_by_tag_id,
        )


class TagSearchResultBuilder:
    """Build a single search result row from preloaded data."""

    def __init__(
        self,
        *,
        format_id: int,
        resolve_preferred: bool,
        logger: Logger | None = None,
    ) -> None:
        self.format_id = format_id
        self.resolve_preferred = resolve_preferred
        self.logger = logger

    def build_row(self, tag_id: int, preloaded: PreloadedData) -> TagSearchRow | None:
        tag_obj = preloaded.tags_by_id.get(tag_id)
        if not tag_obj:
            return None

        status_info = self._resolve_status_info(
            tag_id,
            preloaded.status_by_tag_format,
            preloaded.type_name_by_key,
            preloaded.usage_by_key,
        )
        if status_info is None:
            return None

        resolved_tag_id, tag_obj = self._resolve_preferred_tag(
            tag_id,
            status_info["preferred_tag_id"],
            preloaded.tags_by_id,
            tag_obj,
        )
        trans_dict = self._build_translations(resolved_tag_id, preloaded.trans_by_tag_id)
        format_statuses = self._build_format_statuses(
            resolved_tag_id,
            preloaded.statuses_by_tag_id,
            preloaded.format_name_by_id,
            preloaded.usage_by_key,
            preloaded.type_name_by_key,
        )

        return {
            "tag_id": resolved_tag_id,
            "tag": tag_obj.tag,
            "source_tag": tag_obj.source_tag,
            "usage_count": status_info["usage_count"],
            "alias": status_info["is_alias"],
            "deprecated": status_info["deprecated"],
            "type_id": status_info["resolved_type_id"],
            "type_name": status_info["resolved_type_name"],
            "translations": trans_dict,
            "format_statuses": format_statuses,
        }

    def _resolve_status_info(
        self,
        tag_id: int,
        status_by_tag_format: dict[tuple[int, int], TagStatus],
        type_name_by_key: dict[tuple[int, int], str],
        usage_by_key: dict[tuple[int, int], int],
    ) -> StatusInfo | None:
        usage_count = 0
        is_alias = False
        resolved_type_name = ""
        resolved_type_id = None
        preferred_tag_id = tag_id
        deprecated = False

        if self.format_id:
            status_obj = status_by_tag_format.get((tag_id, self.format_id))
            if status_obj:
                if status_obj.alias is None:
                    if self.logger:
                        self.logger.warning(
                            "[search_tags] alias=NULL detected (tag_id=%s, format_id=%s).",
                            tag_id,
                            self.format_id,
                        )
                    return None
                is_alias = status_obj.alias
                preferred_tag_id = status_obj.preferred_tag_id
                deprecated = bool(status_obj.deprecated)
                resolved_type_name = type_name_by_key.get((self.format_id, status_obj.type_id), "")
            resolved_type_id = status_obj.type_id if status_obj else None

            usage_count = usage_by_key.get((tag_id, self.format_id), 0)

        return {
            "usage_count": usage_count,
            "is_alias": is_alias,
            "resolved_type_name": resolved_type_name,
            "resolved_type_id": resolved_type_id,
            "preferred_tag_id": preferred_tag_id,
            "deprecated": deprecated,
        }

    def _resolve_preferred_tag(
        self,
        tag_id: int,
        preferred_tag_id: int,
        tags_by_id: dict[int, Tag],
        tag_obj: Tag,
    ) -> tuple[int, Tag]:
        resolved_tag_id = tag_id
        if self.resolve_preferred and self.format_id and preferred_tag_id != tag_id:
            preferred_obj = tags_by_id.get(preferred_tag_id)
            if preferred_obj:
                return preferred_tag_id, preferred_obj
        return resolved_tag_id, tag_obj

    def _build_translations(
        self,
        resolved_tag_id: int,
        trans_by_tag_id: dict[int, list[TagTranslation]],
    ) -> dict[str, list[str]]:
        trans_dict: dict[str, list[str]] = {}
        translations = trans_by_tag_id.get(resolved_tag_id, [])
        for tr in translations:
            if tr.language and tr.translation:
                trans_dict.setdefault(tr.language, []).append(tr.translation)
        return trans_dict

    def _build_format_statuses(
        self,
        resolved_tag_id: int,
        statuses_by_tag_id: dict[int, list[TagStatus]],
        format_name_by_id: dict[int, str],
        usage_by_key: dict[tuple[int, int], int],
        type_name_by_key: dict[tuple[int, int], str],
    ) -> dict[str, dict[str, object]]:
        format_statuses: dict[str, dict[str, object]] = {}
        for status in statuses_by_tag_id.get(resolved_tag_id, []):
            fmt_name = format_name_by_id.get(status.format_id)
            if not fmt_name:
                continue
            format_statuses[fmt_name] = {
                "alias": status.alias,
                "deprecated": bool(status.deprecated),
                "usage_count": usage_by_key.get((status.tag_id, status.format_id), 0),
                "type_id": status.type_id,
                "type_name": type_name_by_key.get((status.format_id, status.type_id), ""),
                "preferred_tag_id": status.preferred_tag_id,
            }
        return format_statuses
