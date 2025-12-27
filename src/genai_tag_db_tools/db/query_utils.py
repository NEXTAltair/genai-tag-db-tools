from logging import Logger

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
from genai_tag_db_tools.models import TagSearchRow


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

    def __init__(self, session) -> None:
        self.session = session

    def initial_tag_ids(self, keyword: str, use_like: bool) -> set[int]:
        tag_query = self.session.query(Tag.tag_id)
        translation_query = self.session.query(TagTranslation.tag_id)

        tag_conditions = or_(
            Tag.tag.like(keyword) if use_like else Tag.tag == keyword,
            Tag.source_tag.like(keyword) if use_like else Tag.source_tag == keyword,
        )
        tag_query = tag_query.filter(tag_conditions)

        translation_condition = (
            TagTranslation.translation.like(keyword) if use_like else TagTranslation.translation == keyword
        )
        translation_query = translation_query.filter(translation_condition)

        tag_ids = {row[0] for row in tag_query.all()}
        translation_ids = {row[0] for row in translation_query.all()}
        return tag_ids | translation_ids

    def initial_tag_ids_for_keywords(self, keywords: list[str]) -> dict[str, set[int]]:
        if not keywords:
            return {}

        keyword_set = set(keywords)
        tag_rows = (
            self.session.query(Tag.tag_id, Tag.tag, Tag.source_tag)
            .filter(or_(Tag.tag.in_(keyword_set), Tag.source_tag.in_(keyword_set)))
            .all()
        )
        trans_rows = (
            self.session.query(TagTranslation.tag_id, TagTranslation.translation)
            .filter(TagTranslation.translation.in_(keyword_set))
            .all()
        )

        tag_ids_by_keyword: dict[str, set[int]] = {keyword: set() for keyword in keyword_set}
        for tag_id, tag, source_tag in tag_rows:
            if tag in tag_ids_by_keyword:
                tag_ids_by_keyword[tag].add(tag_id)
            if source_tag in tag_ids_by_keyword:
                tag_ids_by_keyword[source_tag].add(tag_id)
        for tag_id, translation in trans_rows:
            if translation in tag_ids_by_keyword:
                tag_ids_by_keyword[translation].add(tag_id)

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

    def __init__(self, session) -> None:
        self.session = session

    def load(self, tag_ids: set[int]) -> dict[str, object]:
        initial_status_rows = self.session.query(TagStatus).filter(TagStatus.tag_id.in_(tag_ids)).all()
        preferred_ids = {
            row.preferred_tag_id for row in initial_status_rows if row.preferred_tag_id is not None
        }
        status_tag_ids = set(tag_ids) | preferred_ids
        status_rows = self.session.query(TagStatus).filter(TagStatus.tag_id.in_(status_tag_ids)).all()
        format_ids = {row.format_id for row in status_rows}
        format_name_by_id = {
            fmt.format_id: fmt.format_name
            for fmt in self.session.query(TagFormat).filter(TagFormat.format_id.in_(format_ids)).all()
        }
        type_name_by_key = {
            (mapping.format_id, mapping.type_id): (mapping.type_name.type_name if mapping.type_name else "")
            for mapping in self.session.query(TagTypeFormatMapping)
            .filter(TagTypeFormatMapping.format_id.in_(format_ids))
            .all()
        }
        usage_by_key = {
            (usage.tag_id, usage.format_id): usage.count
            for usage in self.session.query(TagUsageCounts)
            .filter(TagUsageCounts.tag_id.in_(status_tag_ids))
            .all()
        }
        tags_by_id = {
            t.tag_id: t for t in self.session.query(Tag).filter(Tag.tag_id.in_(status_tag_ids)).all()
        }
        all_translations = (
            self.session.query(TagTranslation).filter(TagTranslation.tag_id.in_(status_tag_ids)).all()
        )
        trans_by_tag_id: dict[int, list[TagTranslation]] = {}
        for tr in all_translations:
            trans_by_tag_id.setdefault(tr.tag_id, []).append(tr)

        status_by_tag_format: dict[tuple[int, int], TagStatus] = {}
        statuses_by_tag_id: dict[int, list[TagStatus]] = {}
        for status in status_rows:
            status_by_tag_format[(status.tag_id, status.format_id)] = status
            statuses_by_tag_id.setdefault(status.tag_id, []).append(status)

        return {
            "preferred_ids": preferred_ids,
            "status_tag_ids": status_tag_ids,
            "status_rows": status_rows,
            "format_name_by_id": format_name_by_id,
            "type_name_by_key": type_name_by_key,
            "usage_by_key": usage_by_key,
            "tags_by_id": tags_by_id,
            "trans_by_tag_id": trans_by_tag_id,
            "status_by_tag_format": status_by_tag_format,
            "statuses_by_tag_id": statuses_by_tag_id,
        }


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

    def build_row(self, tag_id: int, preloaded: dict[str, object]) -> TagSearchRow | None:
        format_name_by_id = preloaded["format_name_by_id"]
        type_name_by_key = preloaded["type_name_by_key"]
        usage_by_key = preloaded["usage_by_key"]
        tags_by_id = preloaded["tags_by_id"]
        trans_by_tag_id = preloaded["trans_by_tag_id"]
        status_by_tag_format = preloaded["status_by_tag_format"]
        statuses_by_tag_id = preloaded["statuses_by_tag_id"]

        tag_obj = tags_by_id.get(tag_id)
        if not tag_obj:
            return None

        status_info = self._resolve_status_info(
            tag_id, status_by_tag_format, type_name_by_key, usage_by_key
        )
        if status_info is None:
            return None

        resolved_tag_id, tag_obj = self._resolve_preferred_tag(
            tag_id,
            status_info["preferred_tag_id"],
            tags_by_id,
            tag_obj,
        )
        trans_dict = self._build_translations(resolved_tag_id, trans_by_tag_id)
        format_statuses = self._build_format_statuses(
            resolved_tag_id,
            statuses_by_tag_id,
            format_name_by_id,
            usage_by_key,
            type_name_by_key,
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
    ) -> dict[str, object] | None:
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
            }
        return format_statuses
