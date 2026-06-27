# genai_tag_db_tools.db.overlay_reader
from __future__ import annotations

from collections.abc import Callable
from logging import getLogger

from sqlalchemy import func
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.query_utils import normalize_search_keyword
from genai_tag_db_tools.db.schema import (
    Tag,
    TagStatus,
    TagTranslation,
    TagUsageCounts,
    UserTag,
    UserTagStatusPatch,
)
from genai_tag_db_tools.models import TagSearchRow


class OverlayTagReader:
    """USER_TAGS / USER_TAG_STATUS_PATCH を読み取る読み取り専用リポジトリ。

    TagReader と同じ公開インターフェースを実装し、MergedTagReader の user_repo として機能する。
    format / translation 系メソッドはフェーズ2以降で実装予定のため空 stub を置く。
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self.logger = getLogger(__name__)
        self.session_factory = session_factory

    # ------------------------------------------------------------------
    # タグ取得 (USER_TAGS)
    # ------------------------------------------------------------------

    def get_tag_by_id(self, tag_id: int) -> Tag | None:
        """tag_id で USER_TAGS を検索し、見つかれば detached Tag オブジェクトを返す。"""
        with self.session_factory() as session:
            row = session.query(UserTag).filter(UserTag.tag_id == tag_id).one_or_none()
            if row is None:
                return None
            return Tag(tag_id=row.tag_id, source_tag=row.source_tag, tag=row.tag)

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
        """キーワードで USER_TAGS の tag を検索し、最初に一致した tag_id を返す。"""
        keyword, use_like = normalize_search_keyword(keyword, partial)
        with self.session_factory() as session:
            query = session.query(UserTag)
            if use_like:
                query = query.filter(UserTag.tag.like(keyword))
            else:
                query = query.filter(UserTag.tag == keyword)
            results = query.all()
        if not results:
            return None
        if len(results) == 1:
            return results[0].tag_id
        if use_like:
            return results[0].tag_id
        raise ValueError(f"複数のユーザータグが一致しました: keyword={keyword}")

    def list_tags(self) -> list[Tag]:
        """USER_TAGS 全件を detached Tag オブジェクトのリストとして返す。"""
        with self.session_factory() as session:
            rows = session.query(UserTag).all()
            return [Tag(tag_id=r.tag_id, source_tag=r.source_tag, tag=r.tag) for r in rows]

    def get_all_tag_ids(self) -> list[int]:
        """USER_TAGS の全 tag_id を返す。"""
        with self.session_factory() as session:
            return [r.tag_id for r in session.query(UserTag).all()]

    def get_max_tag_id(self) -> int:
        """USER_TAGS の最大 tag_id を返す。存在しなければ 0。"""
        with self.session_factory() as session:
            max_id = session.query(func.max(UserTag.tag_id)).scalar()
            return int(max_id) if max_id is not None else 0

    def search_tag_ids(self, keyword: str, partial: bool = False) -> list[int]:
        """キーワードに一致する USER_TAGS の tag_id リストを返す。"""
        keyword, use_like = normalize_search_keyword(keyword, partial)
        with self.session_factory() as session:
            query = session.query(UserTag.tag_id)
            if use_like:
                query = query.filter(UserTag.tag.like(keyword))
            else:
                query = query.filter(UserTag.tag == keyword)
            return [row[0] for row in query.all()]

    # ------------------------------------------------------------------
    # ステータス取得 (USER_TAG_STATUS_PATCH)
    # ------------------------------------------------------------------

    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        """USER_TAG_STATUS_PATCH からステータスを取得し、detached TagStatus を返す。"""
        with self.session_factory() as session:
            row = (
                session.query(UserTagStatusPatch)
                .filter(
                    UserTagStatusPatch.target_tag_id == tag_id,
                    UserTagStatusPatch.format_id == format_id,
                )
                .one_or_none()
            )
            if row is None:
                return None
            return TagStatus(
                tag_id=row.target_tag_id,
                format_id=row.format_id,
                type_id=row.type_id,
                alias=row.alias,
                preferred_tag_id=row.preferred_tag_id,
                deprecated=row.deprecated,
                deprecated_at=row.deprecated_at,
            )

    def list_tag_statuses(self, tag_id: int | None = None) -> list[TagStatus]:
        """USER_TAG_STATUS_PATCH を全件 (tag_id 指定時はフィルタ) 取得し TagStatus に変換して返す。"""
        with self.session_factory() as session:
            query = session.query(UserTagStatusPatch)
            if tag_id is not None:
                query = query.filter(UserTagStatusPatch.target_tag_id == tag_id)
            rows = query.all()
            return [
                TagStatus(
                    tag_id=r.target_tag_id,
                    format_id=r.format_id,
                    type_id=r.type_id,
                    alias=r.alias,
                    preferred_tag_id=r.preferred_tag_id,
                    deprecated=r.deprecated,
                    deprecated_at=r.deprecated_at,
                )
                for r in rows
            ]

    # ------------------------------------------------------------------
    # 検索 (USER_TAGS + USER_TAG_STATUS_PATCH)
    # ------------------------------------------------------------------

    def search_tags(
        self,
        keyword: str,
        *,
        partial: bool = False,
        format_name: str | None = None,
        format_names: list[str] | None = None,
        type_name: str | None = None,
        type_names: list[str] | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
        deprecated: bool | None = None,
        resolve_preferred: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TagSearchRow]:
        """USER_TAGS からキーワードマッチするタグを取得し、USER_TAG_STATUS_PATCH でステータスを付与して返す。"""
        keyword, use_like = normalize_search_keyword(keyword, partial)
        with self.session_factory() as session:
            query = session.query(UserTag)
            if use_like:
                query = query.filter(UserTag.tag.like(keyword))
            else:
                query = query.filter(UserTag.tag == keyword)
            if offset:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            user_tags = query.all()

        if not user_tags:
            return []

        tag_ids = [t.tag_id for t in user_tags]
        with self.session_factory() as session:
            patches = (
                session.query(UserTagStatusPatch)
                .filter(UserTagStatusPatch.target_tag_id.in_(tag_ids))
                .all()
            )

        # target_tag_id → list[UserTagStatusPatch] のマップ
        patch_map: dict[int, list[UserTagStatusPatch]] = {}
        for p in patches:
            patch_map.setdefault(p.target_tag_id, []).append(p)

        rows: list[TagSearchRow] = []
        for t in user_tags:
            tag_patches = patch_map.get(t.tag_id, [])
            first_patch = tag_patches[0] if tag_patches else None

            format_statuses: dict[str, dict[str, object]] = {
                str(p.format_id): {
                    "alias": p.alias,
                    "deprecated": p.deprecated,
                    "type_id": p.type_id,
                    "preferred_tag_id": p.preferred_tag_id,
                }
                for p in tag_patches
            }

            row: TagSearchRow = {
                "tag_id": t.tag_id,
                "tag": t.tag,
                "source_tag": t.source_tag,
                "usage_count": 0,
                "alias": first_patch.alias if first_patch else False,
                "deprecated": first_patch.deprecated if first_patch else False,
                "type_id": first_patch.type_id if first_patch else None,
                "type_name": "",
                "translations": {},
                "format_statuses": format_statuses,
            }
            rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # stub メソッド (フェーズ2以降で実装予定)
    # ------------------------------------------------------------------

    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        return []

    def list_translations(self) -> list[TagTranslation]:
        return []

    def get_translations_batch(self, tag_ids: list[int]) -> dict[int, list[TagTranslation]]:
        return {}

    def get_format_name(self, format_id: int) -> str | None:
        return None

    def get_format_id(self, format_name: str) -> int:
        return 0

    def get_format_map(self) -> dict[int, str]:
        return {}

    def get_tag_format_ids(self) -> list[int]:
        return []

    def get_tag_formats(self) -> list[str]:
        return []

    def get_tag_languages(self) -> list[str]:
        return []

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
        return {}

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        return None

    def get_type_name_id(self, type_name: str) -> int | None:
        return None

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return None

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        return None

    def list_usage_counts(
        self, tag_id: int | None = None, format_id: int | None = None
    ) -> list[TagUsageCounts]:
        return []

    def get_tag_types(self, format_id: int) -> list[str]:
        return []

    def get_all_types(self) -> list[str]:
        return []

    def get_unknown_type_tag_ids(self, format_id: int) -> list[int]:
        return []

    def get_metadata_value(self, key: str) -> str | None:
        return None

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, TagSearchRow]:
        return {}
