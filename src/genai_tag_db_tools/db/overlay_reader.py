# genai_tag_db_tools.db.overlay_reader
from __future__ import annotations

from collections.abc import Callable
from logging import getLogger

from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from genai_tag_db_tools.db.query_utils import normalize_search_keyword
from genai_tag_db_tools.db.schema import (
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
    UserTag,
    UserTagStatusPatch,
    UserTagTranslationPatch,
    UserTagUsagePatch,
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
        """USER_TAGS からキーワードマッチするタグを取得し、各 PATCH でステータス・使用回数・翻訳を付与して返す。

        legacy ``TagReader.search_tags`` と同じ契約を満たす:

        - キーワードは ``UserTag.tag`` / ``UserTag.source_tag`` /
          ``USER_TAG_TRANSLATION_PATCH.translation`` に対して照合する (#83)。
        - 完全一致 (``partial=False``) は ``COLLATE NOCASE`` で大文字小文字を無視する (#83)。
        - ``format_names`` / ``type_names`` / ``alias`` / ``deprecated`` フィルタを
          ``USER_TAG_STATUS_PATCH`` に対して適用する (#82)。
        - ``min_usage`` / ``max_usage`` を ``USER_TAG_USAGE_PATCH`` に対して適用し、
          単一 format 指定時は ``usage_count`` を実値で返す (#84)。
        - ``language`` フィルタを ``USER_TAG_TRANSLATION_PATCH`` に対して適用する。
        """
        keyword, use_like = normalize_search_keyword(keyword, partial)
        concrete_format_names = self._concrete_names(
            format_names or ([format_name] if format_name else None)
        )
        concrete_type_names = self._concrete_names(type_names or ([type_name] if type_name else None))

        with self.session_factory() as session:
            # format_id は best-effort 解決にとどめる。USER_TAG_*_PATCH は canonical (base)
            # の format_id を保持するが、user DB は同名 format を別 id で持つことがあるため、
            # format によるタグ除外 (hard filter) は行わず、usage scope / 行レベル値の決定に
            # のみ用いる。format の有無判定は MergedTagReader / 下流の format_statuses に委ねる。
            format_ids = self._format_ids_for_names(session, concrete_format_names)
            type_name_ids = self._type_name_ids_for_names(session, concrete_type_names)
            if concrete_type_names and not type_name_ids:
                return []

            user_tags = self._keyword_matched_user_tags(session, keyword, use_like)
            if not user_tags:
                return []
            tag_by_id = {t.tag_id: t for t in user_tags}
            candidate_ids = set(tag_by_id)

            status_by_tag = self._load_status_patches(session, candidate_ids)
            usage_by_tag = self._load_usage_patches(session, candidate_ids)
            trans_by_tag = self._load_translation_patches(session, candidate_ids)
            type_map = self._load_type_name_map(session)

            kept_ids: list[int] = []
            for tag_id in sorted(candidate_ids):
                patches = status_by_tag.get(tag_id, [])
                if not self._status_filter_ok(patches, type_map, type_name_ids, alias, deprecated):
                    continue
                if not self._usage_filter_ok(
                    usage_by_tag.get(tag_id, []), format_ids, min_usage, max_usage
                ):
                    continue
                if not self._language_filter_ok(trans_by_tag.get(tag_id, []), language):
                    continue
                kept_ids.append(tag_id)

            if offset:
                kept_ids = kept_ids[offset:]
            if limit is not None:
                kept_ids = kept_ids[:limit]

            single_format_id = format_ids[0] if len(format_ids) == 1 else 0
            return [
                self._build_search_row(
                    tag_by_id[tag_id],
                    status_by_tag.get(tag_id, []),
                    usage_by_tag.get(tag_id, []),
                    trans_by_tag.get(tag_id, []),
                    type_map,
                    single_format_id,
                )
                for tag_id in kept_ids
            ]

    # ------------------------------------------------------------------
    # search_tags ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _concrete_names(names: list[str] | None) -> list[str]:
        """ "all" / 空文字を除いた具体的なフィルタ名のみを返す。"""
        if not names:
            return []
        return [name for name in names if name and name.lower() != "all"]

    def _format_ids_for_names(self, session: Session, names: list[str]) -> list[int]:
        if not names:
            return []
        try:
            rows = session.query(TagFormat.format_id).filter(TagFormat.format_name.in_(names)).all()
        except OperationalError:
            return []
        return [row[0] for row in rows]

    def _type_name_ids_for_names(self, session: Session, names: list[str]) -> list[int]:
        if not names:
            return []
        try:
            rows = session.query(TagTypeName.type_name_id).filter(TagTypeName.type_name.in_(names)).all()
        except OperationalError:
            return []
        return [row[0] for row in rows]

    def _keyword_matched_user_tags(self, session: Session, keyword: str, use_like: bool) -> list[UserTag]:
        """tag / source_tag / 翻訳テキストのいずれかにキーワードがマッチする UserTag を返す。"""
        tag_cond: ColumnElement[bool]
        translation_cond: ColumnElement[bool]
        if use_like:
            tag_cond = or_(UserTag.tag.like(keyword), UserTag.source_tag.like(keyword))
            translation_cond = UserTagTranslationPatch.translation.like(keyword)
        else:
            tag_cond = or_(
                UserTag.tag.collate("NOCASE") == keyword,
                UserTag.source_tag.collate("NOCASE") == keyword,
            )
            translation_cond = UserTagTranslationPatch.translation.collate("NOCASE") == keyword

        direct = session.query(UserTag).filter(tag_cond).all()
        direct_ids = {t.tag_id for t in direct}

        translation_ids = {
            row[0]
            for row in session.query(UserTagTranslationPatch.target_tag_id).filter(translation_cond).all()
        }
        # 翻訳マッチのうち UserTag に存在するものだけを追加する (base scope の翻訳は除外)。
        extra_ids = translation_ids - direct_ids
        extra = session.query(UserTag).filter(UserTag.tag_id.in_(extra_ids)).all() if extra_ids else []
        return direct + extra

    def _load_status_patches(
        self, session: Session, tag_ids: set[int]
    ) -> dict[int, list[UserTagStatusPatch]]:
        if not tag_ids:
            return {}
        patches = (
            session.query(UserTagStatusPatch).filter(UserTagStatusPatch.target_tag_id.in_(tag_ids)).all()
        )
        result: dict[int, list[UserTagStatusPatch]] = {}
        for p in patches:
            result.setdefault(p.target_tag_id, []).append(p)
        # format_id 昇順で並べ、format 未指定時の「先頭パッチ」を決定的にする。
        for patch_list in result.values():
            patch_list.sort(key=lambda p: p.format_id)
        return result

    def _load_usage_patches(
        self, session: Session, tag_ids: set[int]
    ) -> dict[int, list[UserTagUsagePatch]]:
        if not tag_ids:
            return {}
        rows = session.query(UserTagUsagePatch).filter(UserTagUsagePatch.target_tag_id.in_(tag_ids)).all()
        result: dict[int, list[UserTagUsagePatch]] = {}
        for r in rows:
            result.setdefault(r.target_tag_id, []).append(r)
        return result

    def _load_translation_patches(
        self, session: Session, tag_ids: set[int]
    ) -> dict[int, list[UserTagTranslationPatch]]:
        if not tag_ids:
            return {}
        rows = (
            session.query(UserTagTranslationPatch)
            .filter(UserTagTranslationPatch.target_tag_id.in_(tag_ids))
            .all()
        )
        result: dict[int, list[UserTagTranslationPatch]] = {}
        for r in rows:
            result.setdefault(r.target_tag_id, []).append(r)
        return result

    def _load_type_name_map(self, session: Session) -> dict[tuple[int, int], tuple[int, str]]:
        """(format_id, type_id) → (type_name_id, type_name) のマップを返す。"""
        try:
            rows = (
                session.query(
                    TagTypeFormatMapping.format_id,
                    TagTypeFormatMapping.type_id,
                    TagTypeFormatMapping.type_name_id,
                    TagTypeName.type_name,
                )
                .join(TagTypeName, TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id)
                .all()
            )
        except OperationalError:
            return {}
        return {
            (int(format_id), int(type_id)): (int(type_name_id), type_name)
            for format_id, type_id, type_name_id, type_name in rows
        }

    def _status_filter_ok(
        self,
        patches: list[UserTagStatusPatch],
        type_map: dict[tuple[int, int], tuple[int, str]],
        type_name_ids: list[int],
        alias: bool | None,
        deprecated: bool | None,
    ) -> bool:
        """alias / deprecated / type_names フィルタを USER_TAG_STATUS_PATCH に適用する。

        legacy ``filtered_tag_ids`` の status 判定に準ずる。format による除外は行わない
        (canonical format_id を name から解決できないため、search_tags の docstring 参照)。
        """
        if not type_name_ids and alias is None and deprecated is None:
            return True

        if not type_name_ids:
            if (alias is True or deprecated is True) and not any(
                (alias is not True or p.alias is True)
                and (deprecated is not True or bool(p.deprecated) is True)
                for p in patches
            ):
                return False
            if alias is False and any(p.alias is True for p in patches):
                return False
            if deprecated is False and any(bool(p.deprecated) is True for p in patches):
                return False
            return True

        for p in patches:
            mapping = type_map.get((p.format_id, p.type_id))
            if mapping is None or mapping[0] not in type_name_ids:
                continue
            if alias is not None and p.alias is not alias:
                continue
            if deprecated is not None and bool(p.deprecated) is not deprecated:
                continue
            return True
        return False

    def _usage_filter_ok(
        self,
        usages: list[UserTagUsagePatch],
        format_ids: list[int],
        min_usage: int | None,
        max_usage: int | None,
    ) -> bool:
        if min_usage is None and max_usage is None:
            return True

        def in_scope(usage: UserTagUsagePatch) -> bool:
            return not format_ids or usage.format_id in format_ids

        matching = any(
            in_scope(usage)
            and (min_usage is None or usage.count >= min_usage)
            and (max_usage is None or usage.count <= max_usage)
            for usage in usages
        )
        if matching:
            return True
        # usage パッチが無いタグは、しきい値が 0 を含むときのみ残す (legacy と同じ挙動)。
        include_missing = (min_usage is None or min_usage <= 0) and (max_usage is None or max_usage >= 0)
        if include_missing and not any(in_scope(usage) for usage in usages):
            return True
        return False

    def _language_filter_ok(
        self, translations: list[UserTagTranslationPatch], language: str | None
    ) -> bool:
        if not language or language.lower() == "all":
            return True
        return any(t.language == language for t in translations)

    def _build_search_row(
        self,
        tag: UserTag,
        patches: list[UserTagStatusPatch],
        usages: list[UserTagUsagePatch],
        translations: list[UserTagTranslationPatch],
        type_map: dict[tuple[int, int], tuple[int, str]],
        single_format_id: int,
    ) -> TagSearchRow:
        usage_by_format = {u.format_id: u.count for u in usages}

        if single_format_id:
            active = next((p for p in patches if p.format_id == single_format_id), None)
        else:
            active = patches[0] if patches else None

        if active is not None:
            mapping = type_map.get((active.format_id, active.type_id))
            row_alias = active.alias
            row_deprecated = bool(active.deprecated)
            row_type_id: int | None = active.type_id
            row_type_name = mapping[1] if mapping else ""
            # legacy 同様、単一 format 指定時のみ usage_count を実値で返す。
            row_usage = usage_by_format.get(active.format_id, 0) if single_format_id else 0
        else:
            row_alias = False
            row_deprecated = False
            row_type_id = None
            row_type_name = ""
            row_usage = 0

        translations_dict: dict[str, list[str]] = {}
        for t in translations:
            if t.language and t.translation:
                translations_dict.setdefault(t.language, []).append(t.translation)

        format_statuses: dict[str, dict[str, object]] = {}
        for p in patches:
            mapping = type_map.get((p.format_id, p.type_id))
            format_statuses[str(p.format_id)] = {
                "alias": p.alias,
                "deprecated": bool(p.deprecated),
                "usage_count": usage_by_format.get(p.format_id, 0),
                "type_id": p.type_id,
                "type_name": mapping[1] if mapping else "",
                "preferred_tag_id": p.preferred_tag_id,
            }

        return {
            "tag_id": tag.tag_id,
            "tag": tag.tag,
            "source_tag": tag.source_tag,
            "usage_count": row_usage,
            "alias": row_alias,
            "deprecated": row_deprecated,
            "type_id": row_type_id,
            "type_name": row_type_name,
            "translations": translations_dict,
            "format_statuses": format_statuses,
        }

    # ------------------------------------------------------------------
    # 翻訳取得 (USER_TAG_TRANSLATION_PATCH)
    # ------------------------------------------------------------------

    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        """USER_TAG_TRANSLATION_PATCH から翻訳を取得し TagTranslation オブジェクトに変換する。"""
        with self.session_factory() as session:
            rows = (
                session.query(UserTagTranslationPatch)
                .filter(
                    UserTagTranslationPatch.target_tag_id == tag_id,
                )
                .all()
            )
            return [
                TagTranslation(
                    translation_id=r.patch_id,
                    tag_id=r.target_tag_id,
                    language=r.language,
                    translation=r.translation,
                )
                for r in rows
            ]

    def list_translations(self) -> list[TagTranslation]:
        with self.session_factory() as session:
            rows = session.query(UserTagTranslationPatch).all()
            return [
                TagTranslation(
                    translation_id=r.patch_id,
                    tag_id=r.target_tag_id,
                    language=r.language,
                    translation=r.translation,
                )
                for r in rows
            ]

    def get_translations_batch(self, tag_ids: list[int]) -> dict[int, list[TagTranslation]]:
        """複数 tag_id の翻訳をバッチ取得する。"""
        if not tag_ids:
            return {}
        with self.session_factory() as session:
            rows = (
                session.query(UserTagTranslationPatch)
                .filter(
                    UserTagTranslationPatch.target_tag_id.in_(tag_ids),
                )
                .all()
            )
        result: dict[int, list[TagTranslation]] = {}
        for r in rows:
            result.setdefault(r.target_tag_id, []).append(
                TagTranslation(
                    translation_id=r.patch_id,
                    tag_id=r.target_tag_id,
                    language=r.language,
                    translation=r.translation,
                )
            )
        return result

    def get_format_name(self, format_id: int) -> str | None:
        try:
            with self.session_factory() as session:
                row = (
                    session.query(TagFormat.format_name)
                    .filter(TagFormat.format_id == format_id)
                    .one_or_none()
                )
        except OperationalError:
            return None
        return row[0] if row else None

    def get_format_id(self, format_name: str) -> int:
        try:
            with self.session_factory() as session:
                row = (
                    session.query(TagFormat.format_id)
                    .filter(TagFormat.format_name == format_name)
                    .one_or_none()
                )
        except OperationalError:
            return 0
        return int(row[0]) if row else 0

    def get_format_map(self) -> dict[int, str]:
        try:
            with self.session_factory() as session:
                rows = session.query(TagFormat.format_id, TagFormat.format_name).all()
        except OperationalError:
            return {}
        return {int(format_id): format_name for format_id, format_name in rows}

    def get_tag_format_ids(self) -> list[int]:
        return sorted(self.get_format_map())

    def get_tag_formats(self) -> list[str]:
        return sorted(self.get_format_map().values())

    def get_tag_languages(self) -> list[str]:
        return []

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
        try:
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
        except OperationalError:
            return {}
        return {(int(format_id), int(type_id)): type_name for format_id, type_id, type_name in rows}

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        try:
            with self.session_factory() as session:
                row = (
                    session.query(TagTypeName.type_name)
                    .join(
                        TagTypeFormatMapping,
                        TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id,
                    )
                    .filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeFormatMapping.type_id == type_id,
                    )
                    .one_or_none()
                )
        except OperationalError:
            return None
        return row[0] if row else None

    def get_type_name_id(self, type_name: str) -> int | None:
        try:
            with self.session_factory() as session:
                row = (
                    session.query(TagTypeName.type_name_id)
                    .filter(TagTypeName.type_name == type_name)
                    .one_or_none()
                )
        except OperationalError:
            return None
        return int(row[0]) if row else None

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        try:
            with self.session_factory() as session:
                row = (
                    session.query(TagTypeFormatMapping.type_id)
                    .join(
                        TagTypeName,
                        TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id,
                    )
                    .filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeName.type_name == type_name,
                    )
                    .one_or_none()
                )
        except OperationalError:
            return None
        return int(row[0]) if row else None

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        """USER_TAG_USAGE_PATCH から usage count を取得する。"""
        with self.session_factory() as session:
            row = (
                session.query(UserTagUsagePatch)
                .filter(
                    UserTagUsagePatch.target_tag_id == tag_id,
                    UserTagUsagePatch.format_id == format_id,
                )
                .one_or_none()
            )
            return row.count if row is not None else None

    def get_usage_counts_batch(self, tag_ids: list[int]) -> dict[int, dict[int, int]]:
        """USER_TAG_USAGE_PATCH から複数 tag_id の format 別 usage を一括取得する。

        :meth:`TagReader.get_usage_counts_batch` と同じ
        ``{tag_id: {format_id: count}}`` 形式で返す (LoRAIro #990 Phase 3)。
        SQLite の変数上限 (999) 対策として 900 件ずつチャンク分割する
        (MergedTagReader が全 tag_ids を委譲するため overlay 側でも分割が必要)。
        """
        if not tag_ids:
            return {}
        _SQLITE_IN_LIMIT = 900
        with self.session_factory() as session:
            rows: list[UserTagUsagePatch] = []
            for i in range(0, len(tag_ids), _SQLITE_IN_LIMIT):
                chunk = tag_ids[i : i + _SQLITE_IN_LIMIT]
                rows.extend(
                    session.query(UserTagUsagePatch)
                    .filter(UserTagUsagePatch.target_tag_id.in_(chunk))
                    .all()
                )
        result: dict[int, dict[int, int]] = {}
        for row in rows:
            result.setdefault(row.target_tag_id, {})[row.format_id] = row.count
        return result

    def list_usage_counts(
        self, tag_id: int | None = None, format_id: int | None = None
    ) -> list[TagUsageCounts]:
        """USER_TAG_USAGE_PATCH を TagUsageCounts オブジェクトに変換して返す。"""
        with self.session_factory() as session:
            query = session.query(UserTagUsagePatch)
            if tag_id is not None:
                query = query.filter(UserTagUsagePatch.target_tag_id == tag_id)
            if format_id is not None:
                query = query.filter(UserTagUsagePatch.format_id == format_id)
            rows = query.all()
            return [
                TagUsageCounts(tag_id=r.target_tag_id, format_id=r.format_id, count=r.count) for r in rows
            ]

    def get_tag_types(self, format_id: int) -> list[str]:
        """指定 format で使われている type_name の一覧を返す。

        ``TAG_TYPE_FORMAT_MAPPING JOIN TAG_TYPE_NAME`` を ``format_id`` で絞り込み、
        distinct な type_name を返す。
        """
        try:
            with self.session_factory() as session:
                rows = (
                    session.query(TagTypeName.type_name)
                    .join(
                        TagTypeFormatMapping,
                        TagTypeName.type_name_id == TagTypeFormatMapping.type_name_id,
                    )
                    .filter(TagTypeFormatMapping.format_id == format_id)
                    .distinct()
                    .all()
                )
        except OperationalError:
            return []
        return [row[0] for row in rows]

    def get_all_types(self) -> list[str]:
        """user DB の ``TAG_TYPE_NAME.type_name`` を全件返す。"""
        try:
            with self.session_factory() as session:
                rows = session.query(TagTypeName.type_name).all()
        except OperationalError:
            return []
        return [row[0] for row in rows]

    def get_unknown_type_tag_ids(self, format_id: int) -> list[int]:
        """指定 format で type_name="unknown" にマップされる tag_id 一覧を返す。

        ``TAG_TYPE_NAME`` から "unknown" の type_name_id を解決し、
        ``TAG_TYPE_FORMAT_MAPPING`` で当該 format の type_id を求めた上で、
        ``USER_TAG_STATUS_PATCH`` の target_tag_id を重複なく返す。
        """
        try:
            with self.session_factory() as session:
                unknown_type = (
                    session.query(TagTypeName.type_name_id)
                    .filter(TagTypeName.type_name == "unknown")
                    .one_or_none()
                )
                if unknown_type is None:
                    return []

                mapping = (
                    session.query(TagTypeFormatMapping.type_id)
                    .filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeFormatMapping.type_name_id == unknown_type[0],
                    )
                    .one_or_none()
                )
                if mapping is None:
                    return []

                rows = (
                    session.query(UserTagStatusPatch.target_tag_id)
                    .filter(
                        UserTagStatusPatch.format_id == format_id,
                        UserTagStatusPatch.type_id == mapping[0],
                    )
                    .distinct()
                    .all()
                )
        except OperationalError:
            return []
        return [row[0] for row in rows]

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

    def search_tags_bulk_all(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, list[TagSearchRow]]:
        # search_tags_bulk と同様スタブ。user 行は MergedTagReader が
        # _apply_user_patches_to_search_rows で base 行へパッチ適用する (#998)。
        return {}
