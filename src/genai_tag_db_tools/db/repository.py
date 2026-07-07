from collections.abc import Callable, Sequence
from datetime import datetime
from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from genai_tag_db_tools.db.overlay_reader import OverlayTagReader

import polars as pl
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.query_utils import (
    TAG_ID_IN_CHUNK,
    TagSearchPreloader,
    TagSearchQueryBuilder,
    TagSearchResultBuilder,
    contains_like_pattern,
    invalidate_case_exception_cache,
    normalize_search_keyword,
)
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
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

    def list_tag_rows_by_length(
        self,
        min_length: int,
        max_length: int,
        any_substrings: Sequence[str] | None = None,
    ) -> list[tuple[int, str]]:
        """タグ文字列長が [min_length, max_length] の (tag_id, tag) タプルを返す。

        typo 候補探索 (#118) 用の軽量列挙。編集距離 <= k の候補は長さ差 <= k が
        必要条件なので、SQL 側の長さ窓で候補を絞り、ORM エンティティを実体化しない
        タプル取得で全件走査のコストを抑える。

        Args:
            min_length: タグ文字列長の下限 (両端含む)。
            max_length: タグ文字列長の上限 (両端含む)。
            any_substrings: 指定時、いずれかを部分文字列として含む行に絞る
                (`LIKE '%s%'` の OR)。編集距離 <= k ならクエリを k+1 分割した
                部分文字列の少なくとも1つが候補に無傷で含まれる (鳩の巣原理) ため、
                呼び出し側はこの必要条件で候補を大幅に絞れる。

        Returns:
            条件を満たす (tag_id, tag) タプルのリスト。
        """
        with self.session_factory() as session:
            query = session.query(Tag.tag_id, Tag.tag).filter(
                func.length(Tag.tag).between(min_length, max_length)
            )
            if any_substrings:
                query = query.filter(
                    or_(*[Tag.tag.like(contains_like_pattern(s), escape="\\") for s in any_substrings])
                )
            return [(tag_id, tag) for tag_id, tag in query.all()]

    def list_existing_tag_ids(self, tag_ids: Sequence[int]) -> set[int]:
        """指定 tag_id のうち TAGS に存在するものを返す (#118)。

        MergedTagReader が絞り込み結果の shadow 検証 (上位リポに同 tag_id の行が
        存在するか) に使う。PK インデックス参照の IN クエリを SQLite の bind 変数
        上限に収まるチャンクで実行する。

        Args:
            tag_ids: 存在確認する tag_id の列。

        Returns:
            存在した tag_id の集合。
        """
        existing: set[int] = set()
        with self.session_factory() as session:
            for start in range(0, len(tag_ids), TAG_ID_IN_CHUNK):
                chunk = list(tag_ids[start : start + TAG_ID_IN_CHUNK])
                rows = session.query(Tag.tag_id).filter(Tag.tag_id.in_(chunk)).all()
                existing.update(tag_id for (tag_id,) in rows)
        return existing

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

    def get_type_name_id(self, type_name: str) -> int | None:
        """type_nameからTAG_TYPE_NAMEテーブルのtype_name_idを取得する。

        注意: 返り値はformat固有のtype_idではなく、グローバルなtype_name_idである。
        format固有のtype_idが必要な場合は get_type_id_for_format() を使用すること。

        Args:
            type_name: タイプ名文字列。

        Returns:
            type_name_id。見つからない場合はNone。
        """
        with self.session_factory() as session:
            type_obj = session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            return type_obj.type_name_id if type_obj else None

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        """type_nameとformat_idからformat固有のtype_idを取得する。

        TAG_TYPE_NAME → TAG_TYPE_FORMAT_MAPPING を結合して解決する。

        Args:
            type_name: タイプ名文字列。
            format_id: フォーマットID。

        Returns:
            format固有のtype_id。マッピングが存在しない場合はNone。
        """
        with self.session_factory() as session:
            type_obj = session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            if not type_obj:
                return None
            mapping = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_name_id == type_obj.type_name_id,
                )
                .first()
            )
            return mapping.type_id if mapping else None

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

    def get_translations_batch(self, tag_ids: list[int]) -> dict[int, list[TagTranslation]]:
        """複数タグIDの翻訳を一括取得する。

        N+1クエリを回避するため IN 句で一括取得し、tag_id をキーにした辞書で返す。
        SQLite の変数上限 (999) 対策として 900件ずつチャンク分割してクエリを発行する。

        Args:
            tag_ids: 翻訳を取得するタグIDのリスト。空リストの場合は空辞書を返す。

        Returns:
            tag_id をキーとする TagTranslation リストの辞書。
            翻訳が存在しない tag_id はキーに含まれない。
        """
        if not tag_ids:
            return {}
        _SQLITE_IN_LIMIT = 900
        with self.session_factory() as session:
            rows: list[TagTranslation] = []
            for i in range(0, len(tag_ids), _SQLITE_IN_LIMIT):
                chunk = tag_ids[i : i + _SQLITE_IN_LIMIT]
                rows.extend(session.query(TagTranslation).filter(TagTranslation.tag_id.in_(chunk)).all())
        result: dict[int, list[TagTranslation]] = {}
        for tr in rows:
            result.setdefault(tr.tag_id, []).append(tr)
        return result

    def get_usage_counts_batch(self, tag_ids: list[int]) -> dict[int, dict[int, int]]:
        """複数タグIDの format 別使用回数を一括取得する (LoRAIro #990 Phase 3)。

        N+1 クエリを回避するため IN 句で一括取得し、tag_id をキーに
        ``{format_id: count}`` のネスト辞書で返す。表示言語とは独立した「使用頻度」
        第2軸を chip に補助表示するための読み取り専用 API。``format_id`` →
        表示名の解決は呼び出し側が :meth:`get_format_map` で行う (count 取得と
        name 結合の責務を分離する)。SQLite の変数上限 (999) 対策として 900 件ずつ
        チャンク分割してクエリを発行する。

        Args:
            tag_ids: 使用回数を取得するタグIDのリスト。空リストの場合は空辞書を返す。

        Returns:
            tag_id をキーとする ``{format_id: count}`` 辞書のネスト辞書。
            使用回数が存在しない tag_id はキーに含まれない。
        """
        if not tag_ids:
            return {}
        _SQLITE_IN_LIMIT = 900
        with self.session_factory() as session:
            rows: list[TagUsageCounts] = []
            for i in range(0, len(tag_ids), _SQLITE_IN_LIMIT):
                chunk = tag_ids[i : i + _SQLITE_IN_LIMIT]
                rows.extend(session.query(TagUsageCounts).filter(TagUsageCounts.tag_id.in_(chunk)).all())
        result: dict[int, dict[int, int]] = {}
        for row in rows:
            result.setdefault(row.tag_id, {})[row.format_id] = row.count
        return result

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
        keyword, use_like = normalize_search_keyword(keyword, partial)

        with self.session_factory() as session:
            builder = TagSearchQueryBuilder(session)
            resolved_format_names = format_names or ([format_name] if format_name else None)
            resolved_type_names = type_names or ([type_name] if type_name else None)
            tag_ids, format_id = builder.filtered_tag_ids(
                keyword,
                use_like,
                format_names=resolved_format_names,
                type_names=resolved_type_names,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=alias,
                deprecated=deprecated,
                limit=limit,
                offset=offset,
            )
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

    def search_tags_bulk_all(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, list[TagSearchRow]]:
        """`search_tags_bulk` の全マッチ行版。keyword -> マッチ行リストを返す (#998)。

        `search_tags_bulk` は keyword ごとに最初の 1 行だけ返すため、alias / preferred の
        全マッチ行を要する翻訳品質評価に不足する。ロジックは `search_tags_bulk` と同一で、
        keyword ごとに `break` せず全行を集める点だけが異なる。
        """
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

            result: dict[str, list[TagSearchRow]] = {}
            for keyword, ids in tag_ids_by_keyword.items():
                rows = [row_by_input_id[tag_id] for tag_id in sorted(ids) if tag_id in row_by_input_id]
                if rows:
                    result[keyword] = rows

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

        # #124: bulk_insert → reader 読み戻しの 2 段構えは、writer と reader の間に
        # 正規化・可視性のドリフトがあると「挿入は成功したのに id を返せない」
        # (TAG_ID_NOT_FOUND_AFTER_INSERT) 失敗を作る。挿入と id 取得を同一 session で
        # 完結させ、読み戻しに依存しない。
        with self.session_factory() as session:
            existing = session.query(Tag).filter(Tag.tag == tag).one_or_none()
            if existing is not None:
                return existing.tag_id
            new_tag = Tag(source_tag=source_tag, tag=tag)
            session.add(new_tag)
            try:
                session.commit()
            except IntegrityError as e:
                session.rollback()
                # 並行登録に負けた場合は勝者の id を返す
                winner = session.query(Tag).filter(Tag.tag == tag).one_or_none()
                if winner is not None:
                    return winner.tag_id
                msg = ErrorMessages.DB_OPERATION_FAILED.format(error_msg=str(e))
                self.logger.error(msg)
                raise ValueError(msg) from e
            invalidate_case_exception_cache(session.get_bind())
            return new_tag.tag_id

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
            invalidate_case_exception_cache(session.get_bind())

    def delete_tag(self, tag_id: int) -> None:
        with self.session_factory() as session:
            tag_obj = session.get(Tag, tag_id)
            if not tag_obj:
                msg = ErrorMessages.INVALID_TAG_ID_DELETION_ATTEMPT.format(tag_id=tag_id)
                self.logger.error(msg)
                raise ValueError(msg)
            session.delete(tag_obj)
            session.commit()
            invalidate_case_exception_cache(session.get_bind())

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
            invalidate_case_exception_cache(session.get_bind())

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
                invalidate_case_exception_cache(session.get_bind())
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
                    session, tag_id, format_id, effective_type_id, alias, preferred_tag_id, optional_fields
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
    ) -> int:
        """Create a TagTypeFormatMapping if it doesn't exist.

        重複防止ガード:
        - (format_id, type_name_id) が既存なら作成せず既存のtype_idを返す
        - (format_id, type_id) が他type_name_idで使用済みなら次のtype_idへ繰り上げる

        Args:
            format_id: Format ID
            type_id: Type ID (within the format)
            type_name_id: Type name ID (references TagTypeName)
            description: Optional description

        Returns:
            実際に使用されるtype_id（既存マッピングのtype_idまたは新規作成したtype_id）。
        """
        from genai_tag_db_tools.db.schema import TagTypeFormatMapping

        with self.session_factory() as session:
            # ガード1: (format_id, type_name_id) 重複チェック
            mapping_by_name = (
                session.query(TagTypeFormatMapping)
                .filter(
                    TagTypeFormatMapping.format_id == format_id,
                    TagTypeFormatMapping.type_name_id == type_name_id,
                )
                .first()
            )
            if mapping_by_name:
                self.logger.debug(
                    f"Mapping already exists for format_id={format_id}, type_name_id={type_name_id} "
                    f"with type_id={mapping_by_name.type_id}, skipping creation of type_id={type_id}"
                )
                return mapping_by_name.type_id

            # type_id衝突時は次の候補へ繰り上げる
            candidate_type_id = type_id
            while True:
                mapping_by_pk = (
                    session.query(TagTypeFormatMapping)
                    .filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeFormatMapping.type_id == candidate_type_id,
                    )
                    .one_or_none()
                )

                if mapping_by_pk is None:
                    new_mapping = TagTypeFormatMapping(
                        format_id=format_id,
                        type_id=candidate_type_id,
                        type_name_id=type_name_id,
                        description=description,
                    )
                    session.add(new_mapping)
                    session.commit()
                    self.logger.debug(
                        f"Created new TagTypeFormatMapping: format_id={format_id}, "
                        f"type_id={candidate_type_id}, type_name_id={type_name_id}"
                    )
                    return candidate_type_id

                if mapping_by_pk.type_name_id == type_name_id:
                    return mapping_by_pk.type_id

                self.logger.warning(
                    "type_id collision detected for format_id=%s, requested_type_id=%s, "
                    "existing_type_name_id=%s, requested_type_name_id=%s; retrying with next type_id",
                    format_id,
                    candidate_type_id,
                    mapping_by_pk.type_name_id,
                    type_name_id,
                )
                candidate_type_id += 1

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

    def cleanup_duplicate_type_mappings(self, format_id: int) -> int:
        """TAG_TYPE_FORMAT_MAPPINGの(format_id, type_name_id)重複を修復する。

        type_name_id/type_idの混同バグにより生成された重複行を安全に削除する。
        各(format_id, type_name_id)グループで代表type_idを選び、
        TAG_STATUSの参照を代表type_idに更新してから不要行を削除する。

        代表type_id選択ルール:
        - unknownは type_id=0 を優先
        - それ以外は TAG_STATUS で参照中の type_id を優先、なければ最小非0

        Args:
            format_id: クリーンアップ対象のフォーマットID。

        Returns:
            削除された重複行数。
        """
        from sqlalchemy import func

        from genai_tag_db_tools.db.schema import TagStatus, TagTypeFormatMapping, TagTypeName

        deleted_count = 0

        with self.session_factory() as session:
            # (format_id, type_name_id) ごとの重複を検出
            duplicates = (
                session.query(
                    TagTypeFormatMapping.type_name_id,
                    func.count(TagTypeFormatMapping.type_id).label("cnt"),
                )
                .filter(TagTypeFormatMapping.format_id == format_id)
                .group_by(TagTypeFormatMapping.type_name_id)
                .having(func.count(TagTypeFormatMapping.type_id) > 1)
                .all()
            )

            for dup_type_name_id, _ in duplicates:
                # 重複グループの全マッピングを取得
                mappings = (
                    session.query(TagTypeFormatMapping)
                    .filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeFormatMapping.type_name_id == dup_type_name_id,
                    )
                    .all()
                )
                type_ids = [m.type_id for m in mappings]

                # type_nameを取得して代表type_idを選択
                type_name_obj = (
                    session.query(TagTypeName)
                    .filter(TagTypeName.type_name_id == dup_type_name_id)
                    .one_or_none()
                )
                type_name_str = type_name_obj.type_name if type_name_obj else ""

                if type_name_str == "unknown" and 0 in type_ids:
                    representative_type_id = 0
                else:
                    # TAG_STATUSで参照中のtype_idを優先
                    referenced_type_ids = (
                        session.query(TagStatus.type_id)
                        .filter(
                            TagStatus.format_id == format_id,
                            TagStatus.type_id.in_(type_ids),
                        )
                        .distinct()
                        .all()
                    )
                    referenced = {r[0] for r in referenced_type_ids}

                    if referenced:
                        representative_type_id = min(referenced)
                    else:
                        # 参照なし: 最小非0、なければ最小値
                        non_zero = [t for t in type_ids if t != 0]
                        representative_type_id = min(non_zero) if non_zero else min(type_ids)

                # TAG_STATUSを代表type_idに更新
                remove_type_ids = [t for t in type_ids if t != representative_type_id]
                for old_type_id in remove_type_ids:
                    session.query(TagStatus).filter(
                        TagStatus.format_id == format_id,
                        TagStatus.type_id == old_type_id,
                    ).update({TagStatus.type_id: representative_type_id})

                # 不要なマッピング行を削除
                for old_type_id in remove_type_ids:
                    session.query(TagTypeFormatMapping).filter(
                        TagTypeFormatMapping.format_id == format_id,
                        TagTypeFormatMapping.type_id == old_type_id,
                    ).delete()
                    deleted_count += 1

            if deleted_count > 0:
                session.commit()
                self.logger.info(
                    f"Cleaned up {deleted_count} duplicate type mappings for format_id={format_id}"
                )

        return deleted_count

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
            resolved_type_id = self.create_type_format_mapping_if_not_exists(
                format_id=format_id,
                type_id=next_type_id,
                type_name_id=type_name_id,
            )
            cache[type_name] = resolved_type_id
            self.logger.info(
                f"Created new type mapping: format_id={format_id}, "
                f"type_id={resolved_type_id}, type_name={type_name}"
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

    def write_user_translation(self, tag_id: int, language: str, translation: str) -> None:
        """Add a translation overlay for ``tag_id`` to the user database.

        Writes a row into the user DB ``USER_TAG_TRANSLATION_PATCH`` table (never the
        base DB). ``target_scope`` records which tag the overlay points at so the merged
        reader can surface it on the corresponding base/user tag; the row itself always
        lives only in the user DB. Duplicate (scope, tag_id, language, translation) rows
        are ignored.

        Scope is resolved through the injected reader (``get_tag_scope``) when available,
        which checks actual repository membership rather than the numeric offset. This
        avoids mis-tagging a low-id user tag (legacy TAGS path) as base scope. If the
        reader cannot find ``tag_id`` in any scope the write is rejected with
        ``ValueError`` so callers never create an orphan FK-less patch for a stale or
        mistyped id. When no reader is injected the method falls back to the
        ``USER_TAG_ID_OFFSET`` heuristic (no existence validation).

        Args:
            tag_id: Target tag id (base or user scope; scope is resolved automatically).
            language: Language code (e.g. ``ja``).
            translation: Translation string to register.

        Raises:
            ValueError: If a reader is available and ``tag_id`` exists in no scope.

        Example:
            >>> repo = get_default_repository()
            >>> repo.write_user_translation(123, "ja", "青い目")
        """
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        target_scope = self._resolve_patch_scope(tag_id, operation="write_user_translation")
        user_repo = UserTagRepository(self.session_factory)
        user_repo.write_translation_patch(
            target_scope=target_scope,
            target_tag_id=tag_id,
            language=language,
            translation=translation,
        )

    def _resolve_patch_scope(self, tag_id: int, *, operation: str) -> str:
        """patch/preference 書き込み対象タグの scope を解決する (#122)。

        write_user_translation と同一の契約: reader 注入時は実在チェック付きで
        scope を解決し、どの scope にも無ければ ValueError。未注入時は
        USER_TAG_ID_OFFSET ヒューリスティックへ縮退する。
        """
        if self._reader is not None:
            target_scope = self._reader.get_tag_scope(tag_id)
            if target_scope is None:
                # 対象タグがどの scope にも存在しない → orphan 行を書かず拒否する。
                raise ValueError(f"{operation}: tag_id={tag_id} not found in any scope")
            return target_scope
        return "user" if tag_id >= USER_TAG_ID_OFFSET else "base"

    def set_preferred_translation(self, tag_id: int, language: str, translation: str) -> None:
        """タグ x 言語の主訳 (優先翻訳) を user DB overlay へ upsert する (#122)。

        言語ごとに主訳は1つで、既存設定は上書きされる。翻訳候補そのものは追加しない
        (候補の追加は write_user_translation)。

        Args:
            tag_id: 対象タグの tag_id (base / user どちらでも可)。
            language: 言語コード (例: ``ja``)。
            translation: 主訳として表示する翻訳文字列。

        Raises:
            ValueError: reader 注入時に tag_id がどの scope にも存在しない場合。
        """
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        target_scope = self._resolve_patch_scope(tag_id, operation="set_preferred_translation")
        user_repo = UserTagRepository(self.session_factory)
        user_repo.write_translation_preference(
            target_scope=target_scope,
            target_tag_id=tag_id,
            language=language,
            translation=translation,
        )

    def clear_preferred_translation(self, tag_id: int, language: str) -> bool:
        """タグ x 言語の主訳設定を削除する (#122)。

        Args:
            tag_id: 対象タグの tag_id。
            language: 言語コード。

        Returns:
            設定を削除したら True、元々無ければ False。

        Raises:
            ValueError: reader 注入時に tag_id がどの scope にも存在しない場合。
        """
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        target_scope = self._resolve_patch_scope(tag_id, operation="clear_preferred_translation")
        user_repo = UserTagRepository(self.session_factory)
        return user_repo.delete_translation_preference(
            target_scope=target_scope,
            target_tag_id=tag_id,
            language=language,
        )

    def delete_user_translation(self, tag_id: int, language: str, translation: str) -> bool:
        """user DB overlay の翻訳 patch 行を削除する (#121)。

        user 由来の誤登録の取り消しに使う。base DB 由来の翻訳行は削除できない
        (隠すには :meth:`suppress_translation`)。

        Args:
            tag_id: 対象タグの tag_id (base / user どちらでも可)。
            language: 言語コード (例: ``ja``)。
            translation: 削除する翻訳文字列。

        Returns:
            patch 行を削除したら True、元々無ければ False。

        Raises:
            ValueError: reader 注入時に tag_id がどの scope にも存在しない場合。
        """
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        target_scope = self._resolve_patch_scope(tag_id, operation="delete_user_translation")
        user_repo = UserTagRepository(self.session_factory)
        return user_repo.delete_translation_patch(
            target_scope=target_scope,
            target_tag_id=tag_id,
            language=language,
            translation=translation,
        )

    def suppress_translation(self, tag_id: int, language: str, translation: str) -> None:
        """(tag_id, language, translation) を merged 表示から隠す tombstone を書く (#121)。

        base DB は書き換えない。base 由来の誤訳の抑制と、言語付け替え
        (旧言語行の suppress + 新言語での write_user_translation) に使う。
        重複は無視される。

        Args:
            tag_id: 対象タグの tag_id (base / user どちらでも可)。
            language: 隠す翻訳の言語コード。
            translation: 隠す翻訳文字列。

        Raises:
            ValueError: reader 注入時に tag_id がどの scope にも存在しない場合。
        """
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        target_scope = self._resolve_patch_scope(tag_id, operation="suppress_translation")
        user_repo = UserTagRepository(self.session_factory)
        user_repo.write_translation_tombstone(
            target_scope=target_scope,
            target_tag_id=tag_id,
            language=language,
            translation=translation,
        )

    def unsuppress_translation(self, tag_id: int, language: str, translation: str) -> bool:
        """suppress_translation の tombstone を取り消す (#121)。

        Returns:
            tombstone を削除したら True、元々無ければ False。

        Raises:
            ValueError: reader 注入時に tag_id がどの scope にも存在しない場合。
        """
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        target_scope = self._resolve_patch_scope(tag_id, operation="unsuppress_translation")
        user_repo = UserTagRepository(self.session_factory)
        return user_repo.delete_translation_tombstone(
            target_scope=target_scope,
            target_tag_id=tag_id,
            language=language,
            translation=translation,
        )


class MergedTagReader:
    """Read-only view merging base/user repositories."""

    def __init__(
        self,
        base_repo: TagReader | list[TagReader],
        user_repo: "TagReader | OverlayTagReader | None" = None,
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

    def _iter_repos(self) -> "list[TagReader | OverlayTagReader]":
        repos: list[TagReader | OverlayTagReader] = []
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

    def _merge_search_tags_adaptive(
        self,
        keyword: str,
        *,
        limit: int | None,
        offset: int,
        **kwargs: Any,
    ) -> list[TagSearchRow]:
        """Merge search pages after cross-repository deduplication."""
        repos = [*self._iter_base_repos_low_to_high()]
        if self._has_user():
            assert self.user_repo is not None
            repos.append(self.user_repo)

        merged: dict[int, TagSearchRow] = {}

        if limit is None:
            for repo in repos:
                for row in repo.search_tags(keyword, limit=None, offset=0, **kwargs):
                    merged[row["tag_id"]] = row
            rows = [merged[tag_id] for tag_id in sorted(merged)]
            return rows[offset:] if offset else rows

        if limit <= 0:
            return []

        target = offset + limit
        chunk_size = max(target, 1)
        repo_offsets = dict.fromkeys(range(len(repos)), 0)
        exhausted: set[int] = set()

        while len(merged) < target and len(exhausted) < len(repos):
            made_progress = False
            for index, repo in enumerate(repos):
                if index in exhausted:
                    continue
                rows = repo.search_tags(
                    keyword,
                    limit=chunk_size,
                    offset=repo_offsets[index],
                    **kwargs,
                )
                if not rows:
                    exhausted.add(index)
                    continue
                made_progress = True
                repo_offsets[index] += len(rows)
                if len(rows) < chunk_size:
                    exhausted.add(index)
                for row in rows:
                    merged[row["tag_id"]] = row
            if not made_progress:
                break

        rows = [merged[tag_id] for tag_id in sorted(merged)]
        return rows[offset:target]

    def _requested_format_id(
        self,
        format_name: str | None = None,
        format_names: list[str] | None = None,
    ) -> int | None:
        names = format_names or ([format_name] if format_name else [])
        if not names:
            return None
        try:
            return self.get_format_id(names[0])
        except (AttributeError, ValueError):
            return None

    def _format_name_for_id(self, format_id: int) -> str:
        try:
            return self.get_format_name(format_id) or str(format_id)
        except AttributeError:
            return str(format_id)

    def _type_name_for_format_type(self, format_id: int, type_id: int) -> str:
        try:
            return self.get_type_name_by_format_type_id(format_id, type_id) or ""
        except AttributeError:
            return ""

    def _select_active_status(self, patches: list[Any], requested_format_id: int | None) -> Any | None:
        if not patches:
            return None
        if requested_format_id is not None:
            for patch in patches:
                if patch.format_id == requested_format_id:
                    return patch
            return None
        return sorted(patches, key=lambda patch: patch.format_id)[0]

    def _format_status_dict(self, value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _apply_user_patches_to_search_rows(
        self,
        rows: list[TagSearchRow],
        *,
        requested_format_id: int | None = None,
    ) -> list[TagSearchRow]:
        if not rows or not self._has_user():
            return rows
        assert self.user_repo is not None
        tag_ids = {row["tag_id"] for row in rows}
        patched_by_tag: dict[int, list[Any]] = {}
        usage_by_tag: dict[int, list[TagUsageCounts]] = {}
        translations_by_tag = self.user_repo.get_translations_batch(list(tag_ids))
        # tombstone (#121): base 検索行に載ってきた翻訳もマージ時に除外する
        tombstones_by_tag = self._translation_tombstones_batch(list(tag_ids))
        for tag_id in tag_ids:
            patched_by_tag[tag_id] = self.user_repo.list_tag_statuses(tag_id)
            usage_by_tag[tag_id] = self.user_repo.list_usage_counts(tag_id=tag_id)

        patched_rows: list[TagSearchRow] = []
        for row in rows:
            updated = dict(row)
            format_statuses = dict(row.get("format_statuses") or {})

            # 検索行の translations は base 由来値が主 (user patch は overlay 側で
            # scope-aware に除外済みの値が後段でマージされる) ため、base 宛 tombstone
            # のみ適用する (Codex P2: scope 保持)
            hidden = self._hidden_pairs_for_scope(tombstones_by_tag.get(row["tag_id"], set()), "base")
            translations_obj = updated.get("translations")
            if hidden and isinstance(translations_obj, dict):
                filtered: dict[str, list[str]] = {}
                for language, values in cast("dict[str, list[str]]", translations_obj).items():
                    kept = [value for value in values or [] if (language, value) not in hidden]
                    if kept:
                        filtered[language] = kept
                updated["translations"] = filtered

            for usage in usage_by_tag.get(row["tag_id"], []):
                fmt_name = self._format_name_for_id(usage.format_id)
                status = self._format_status_dict(format_statuses.get(fmt_name))
                status["usage_count"] = usage.count
                format_statuses[fmt_name] = status
                if requested_format_id == usage.format_id:
                    updated["usage_count"] = usage.count

            for translation in translations_by_tag.get(row["tag_id"], []):
                if translation.language and translation.translation:
                    translations_obj = updated.get("translations")
                    translations = (
                        dict(cast(dict[str, list[str]], translations_obj))
                        if isinstance(translations_obj, dict)
                        else {}
                    )
                    values = list(translations.get(translation.language) or [])
                    if translation.translation not in values:
                        values.append(translation.translation)
                    translations[translation.language] = values
                    updated["translations"] = translations

            patches = patched_by_tag.get(row["tag_id"], [])
            if not patches:
                updated["format_statuses"] = format_statuses
                patched_rows.append(cast(TagSearchRow, updated))
                continue

            for patch in patches:
                fmt_name = self._format_name_for_id(patch.format_id)
                type_name = self._type_name_for_format_type(patch.format_id, patch.type_id)
                status = self._format_status_dict(format_statuses.get(fmt_name))
                status.update(
                    {
                        "alias": patch.alias,
                        "deprecated": patch.deprecated,
                        "type_id": patch.type_id,
                        "type_name": type_name,
                        "preferred_tag_id": patch.preferred_tag_id,
                    }
                )
                patch_usage = next(
                    (
                        item
                        for item in usage_by_tag.get(row["tag_id"], [])
                        if item.format_id == patch.format_id
                    ),
                    None,
                )
                if patch_usage is not None:
                    status["usage_count"] = patch_usage.count
                format_statuses[fmt_name] = status

            active_patch = self._select_active_status(patches, requested_format_id)
            if active_patch is not None:
                updated["alias"] = active_patch.alias
                updated["deprecated"] = active_patch.deprecated
                updated["type_id"] = active_patch.type_id
                updated["type_name"] = self._type_name_for_format_type(
                    active_patch.format_id,
                    active_patch.type_id,
                )
            updated["format_statuses"] = format_statuses
            patched_rows.append(cast(TagSearchRow, updated))
        return patched_rows

    def _search_row_matches_filters(
        self,
        row: TagSearchRow,
        keyword: str,
        *,
        partial: bool,
        type_name: str | None,
        type_names: list[str] | None,
        language: str | None,
        min_usage: int | None,
        max_usage: int | None,
        alias: bool | None,
        deprecated: bool | None,
    ) -> bool:
        normalized, use_like = normalize_search_keyword(keyword, partial)
        needle = normalized.strip("%").casefold() if use_like else normalized.casefold()
        haystacks = [row["tag"], row.get("source_tag") or ""]
        for values in row.get("translations", {}).values():
            haystacks.extend(values)
        if needle and use_like and not any(needle in value.casefold() for value in haystacks):
            return False
        if needle and not use_like and not any(needle == value.casefold() for value in haystacks):
            return False

        if alias is not None and row["alias"] is not alias:
            return False
        if deprecated is not None and row["deprecated"] is not deprecated:
            return False
        requested_types = type_names or ([type_name] if type_name else [])
        if requested_types and row["type_name"] not in requested_types:
            return False
        if language is not None and language not in row.get("translations", {}):
            return False
        if min_usage is not None and row["usage_count"] < min_usage:
            return False
        if max_usage is not None and row["usage_count"] > max_usage:
            return False
        return True

    def _row_still_matches_keyword(self, row: TagSearchRow, keyword: str) -> bool:
        """tombstone (#121) フィルタ後も keyword に一致しているかを再判定する。

        bulk 経路は base 検索が翻訳一致で keyword→row を対応付けた後に
        `_apply_user_patches_to_search_rows` の tombstone 除外が走るため、
        唯一の一致訳が消えた row を結果から落とす必要がある (Codex P2)。
        """
        return self._search_row_matches_filters(
            row,
            keyword,
            partial=False,
            type_name=None,
            type_names=None,
            language=None,
            min_usage=None,
            max_usage=None,
            alias=None,
            deprecated=None,
        )

    def _base_rows_for_user_translation_matches(
        self,
        keyword: str,
        *,
        partial: bool,
        language: str | None,
    ) -> list[TagSearchRow]:
        if not self._has_user():
            return []
        assert self.user_repo is not None
        normalized, use_like = normalize_search_keyword(keyword, partial)
        needle = normalized.strip("%").casefold() if use_like else normalized.casefold()
        rows: list[TagSearchRow] = []
        for translation in self.user_repo.list_translations():
            if language is not None and translation.language != language:
                continue
            value = translation.translation or ""
            if needle and use_like and needle not in value.casefold():
                continue
            if needle and not use_like and needle != value.casefold():
                continue
            tag = self.get_tag_by_id(translation.tag_id)
            if tag is None:
                continue
            rows.append(
                {
                    "tag_id": tag.tag_id,
                    "tag": tag.tag,
                    "source_tag": tag.source_tag,
                    "usage_count": 0,
                    "alias": False,
                    "deprecated": False,
                    "type_id": None,
                    "type_name": "",
                    "translations": {},
                    "format_statuses": {},
                }
            )
        return rows

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

    def get_tag_scope(self, tag_id: int) -> str | None:
        """tag_id がどの DB (scope) に属するかを判定する。

        数値 offset (USER_TAG_ID_OFFSET) に依存せず、実際にどのリポジトリが
        その tag_id を保持しているかで scope を決める。user_repo を優先し、
        見つかれば "user"、base repos にあれば "base"、どこにも無ければ None。

        Args:
            tag_id: 判定対象のタグID。

        Returns:
            "user" / "base" / None。
        """
        if self._has_user():
            assert self.user_repo is not None
            if self.user_repo.get_tag_by_id(tag_id) is not None:
                return "user"
        for repo in self._iter_base_repos():
            if repo.get_tag_by_id(tag_id) is not None:
                return "base"
        return None

    def get_tag_status(self, tag_id: int, format_id: int) -> TagStatus | None:
        return self._first_found("get_tag_status", tag_id, format_id)

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        return self._first_found("get_usage_count", tag_id, format_id)

    def get_format_name(self, format_id: int) -> str | None:
        return self._first_found("get_format_name", format_id)

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        return self._first_found("get_type_name_by_format_type_id", format_id, type_id)

    def get_type_name_id(self, type_name: str) -> int | None:
        """type_nameからtype_name_idを取得する（複数リポジトリを検索）。"""
        return self._first_found("get_type_name_id", type_name)

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        """type_nameとformat_idからformat固有のtype_idを取得する（複数リポジトリを検索）。"""
        return self._first_found("get_type_id_for_format", type_name, format_id)

    def get_metadata_value(self, key: str) -> str | None:
        return self._first_found("get_metadata_value", key)

    def get_format_id(self, format_name: str) -> int:
        for repo in self._iter_base_repos():
            for format_id, name in repo.get_format_map().items():
                if name == format_name:
                    return format_id
        if self._has_user():
            assert self.user_repo is not None
            for format_id, name in self.user_repo.get_format_map().items():
                if name == format_name:
                    return format_id
        raise ValueError(f"format_name not found: {format_name}")

    # ------------------------------------------------------------------
    # Pattern B: _merge_by_key (全リポから収集、キーで重複排除マージ)
    # ------------------------------------------------------------------

    def list_tags(self) -> list[Tag]:
        return self._merge_by_key("list_tags", lambda t: t.tag_id)

    def list_tag_rows_by_length(
        self,
        min_length: int,
        max_length: int,
        any_substrings: Sequence[str] | None = None,
    ) -> list[tuple[int, str]]:
        """全リポジトリから長さ窓に合う (tag_id, tag) を収集し tag_id でマージする (#118)。

        「マージ勝者の行にフィルタを適用した」結果と一致するよう、優先度順マージの
        後に shadow 検証を行う。リポジトリごとに絞ってから素朴にマージすると、
        上位リポの同 tag_id 行が窓外のとき (絞り込み結果に現れないとき) に下位の
        shadowed 行が漏れ、list_tags() のマージ視点では存在しないタグ文字列を
        返してしまう (Codex P2)。下位リポが勝った tag_id は、より上位のリポに同
        tag_id の行が存在しないこと (= 真の勝者であること) を PK 参照で検証する。

        Args:
            min_length: タグ文字列長の下限 (両端含む)。
            max_length: タグ文字列長の上限 (両端含む)。
            any_substrings: 指定時、いずれかを部分文字列として含む行に絞る。

        Returns:
            マージ視点で有効な行だけを含む (tag_id, tag) タプルのリスト。
        """
        # 優先度 高→低 (user が最優先、base は base_repos[0] が最上位)
        repos: list[TagReader | OverlayTagReader] = []
        if self.user_repo is not None:
            repos.append(self.user_repo)
        repos.extend(self._iter_base_repos())

        merged: dict[int, str] = {}
        winner_level: dict[int, int] = {}
        for level, repo in enumerate(repos):
            for tag_id, tag in repo.list_tag_rows_by_length(min_length, max_length, any_substrings):
                if tag_id not in merged:  # 先勝ち = 上位リポ優先
                    merged[tag_id] = tag
                    winner_level[tag_id] = level

        # shadow 検証: level h より下位で勝った tag_id が repos[h] に存在するなら、
        # 上位の行が窓外だったことを意味する (真の勝者は窓外) ため除外する。
        for level in range(len(repos) - 1):
            lower_winner_ids = [tag_id for tag_id, winner in winner_level.items() if winner > level]
            if not lower_winner_ids:
                continue
            shadowed = repos[level].list_existing_tag_ids(lower_winner_ids)
            for tag_id in shadowed:
                merged.pop(tag_id, None)
                winner_level.pop(tag_id, None)

        return list(merged.items())

    def get_preferred_translations_batch(self, tag_ids: list[int]) -> dict[int, dict[str, str]]:
        """主訳 (優先翻訳) を一括取得する (#122)。

        preference は user overlay にのみ存在するため base repos は参照しない。
        user_repo 未設定、または user_repo が preference を提供しない (legacy
        TagReader 等) 場合は空 dict を返す。

        Args:
            tag_ids: 取得対象の tag_id リスト。

        Returns:
            ``{tag_id: {language: translation}}`` (設定のあるタグのみ)。
        """
        # get_user_tag_reader() は OverlayTagReader を base_repo として単独ラップする
        # (user_repo=None) ため、user_repo だけを見ると user-only 読みで preference が
        # 空になる (Codex P2)。preference を提供できる repo を優先度 低→高 の順に
        # 集め、後勝ちマージ (user が最優先) で畳む。提供 repo が無ければ空 dict。
        result: dict[int, dict[str, str]] = {}
        providers = [*self._iter_base_repos_low_to_high()]
        if self.user_repo is not None:
            providers.append(self.user_repo)
        for repo in providers:
            getter = getattr(repo, "get_preferred_translations_batch", None)
            if getter is None:
                continue
            for tag_id, translations in getter(tag_ids).items():
                result.setdefault(tag_id, {}).update(translations)
        # tombstone (#121) された翻訳を指す preference の除外は、行の target_scope が
        # 分かる OverlayTagReader.get_preferred_translations_batch 側で scope-aware に
        # 行う (マージ出力は scope 帰属を失うため、ここで適用すると base 宛 tombstone が
        # 同 id の user-scope preference まで隠す。Codex P2)
        return result

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

    def _resolve_cross_scope_preferred(
        self,
        rows: list[TagSearchRow],
    ) -> list[TagSearchRow]:
        """search_tags 結果のうち preferred が別 DB にあるものを解決する。

        alias=True の行を対象に全リポをまたいだ preferred tag lookup を行い、
        preferred が見つかれば row を差し替える。

        OverlayTagReader は同一 DB 内の preferred しか解決しないため、
        cross-scope alias (user → base 等) はこのメソッドで補完する。

        Args:
            rows: マージ済みの TagSearchRow リスト。

        Returns:
            preferred 解決後の TagSearchRow リスト。
        """
        result: list[TagSearchRow] = []
        for row in rows:
            if not row["alias"]:
                result.append(row)
                continue

            tag_id = row["tag_id"]
            preferred_tag_id: int | None = None

            # 全リポからステータスを取得して preferred_tag_id を探す
            for repo in self._iter_repos():
                statuses = repo.list_tag_statuses(tag_id)
                for status in statuses:
                    if status.alias and status.preferred_tag_id != tag_id:
                        preferred_tag_id = status.preferred_tag_id
                        break
                if preferred_tag_id is not None:
                    break

            if preferred_tag_id is None or preferred_tag_id == tag_id:
                result.append(row)
                continue

            # preferred tag を全リポから取得
            preferred_tag: Tag | None = None
            for repo in self._iter_repos():
                preferred_tag = repo.get_tag_by_id(preferred_tag_id)
                if preferred_tag is not None:
                    break

            if preferred_tag is not None:
                translations: dict[str, list[str]] = {}
                for translation in self.get_translations(preferred_tag_id):
                    if translation.language and translation.translation:
                        translations.setdefault(translation.language, []).append(translation.translation)
                new_row: TagSearchRow = {
                    "tag_id": preferred_tag_id,
                    "tag": preferred_tag.tag,
                    "source_tag": preferred_tag.source_tag,
                    "usage_count": row["usage_count"],
                    "alias": False,
                    "deprecated": row["deprecated"],
                    "type_id": row["type_id"],
                    "type_name": row["type_name"],
                    "translations": translations,
                    "format_statuses": row["format_statuses"],
                }
                result.append(new_row)
            else:
                result.append(row)
        return result

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
        requested_format_id = self._requested_format_id(format_name, format_names)
        rows = self._merge_search_tags_adaptive(
            keyword,
            limit=None,
            offset=0,
            partial=partial,
            format_name=format_name,
            format_names=format_names,
            type_name=None,
            type_names=None,
            language=None,
            min_usage=None,
            max_usage=None,
            alias=None,
            deprecated=None,
            resolve_preferred=False,
        )
        rows.extend(
            self._base_rows_for_user_translation_matches(
                keyword,
                partial=partial,
                language=language,
            )
        )
        deduped = {row["tag_id"]: row for row in rows}
        rows = self._apply_user_patches_to_search_rows(
            [deduped[tag_id] for tag_id in sorted(deduped)],
            requested_format_id=requested_format_id,
        )
        rows = [
            row
            for row in rows
            if self._search_row_matches_filters(
                row,
                keyword,
                partial=partial,
                type_name=type_name,
                type_names=type_names,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=alias,
                deprecated=deprecated,
            )
        ]
        if limit is not None:
            rows = rows[offset : offset + limit]
        elif offset:
            rows = rows[offset:]
        if resolve_preferred:
            rows = self._resolve_cross_scope_preferred(rows)
            rows = self._dedup_case_variant_user_rows(rows)
        return rows

    def _base_has_case_variant(self, tag: str, *, exclude_tag_id: int) -> bool:
        """いずれかの base repo に ``tag`` と casefold 一致する別 tag_id の canonical タグがあるか。

        base の完全一致検索は case-insensitive のため、``tag`` にマッチした base 行のうち
        ``tag`` 文字列 (canonical) が casefold 一致するものだけを重複とみなす。翻訳や
        source_tag だけがマッチした行 (canonical が別文字列) は重複扱いしない。
        ``exclude_tag_id`` と同じ tag_id の行は「自分自身」なので除外する (legacy 数値衝突で
        base タグ自身が誤って重複判定されるのを防ぐ、Codex P2)。

        Args:
            tag: 判定対象行の canonical タグ文字列。
            exclude_tag_id: 判定対象行の tag_id。この tag_id の base 行は自己一致として無視する。

        Returns:
            別 tag_id の base に case-variant の canonical タグがあれば ``True``。
        """
        needle = tag.casefold()
        for repo in self._iter_base_repos():
            for base_row in repo.search_tags(tag, partial=False):
                if base_row["tag_id"] != exclude_tag_id and base_row["tag"].casefold() == needle:
                    return True
        return False

    def _is_overlay_origin_row(self, row: TagSearchRow) -> bool:
        """行が user overlay 由来かを、数値 ID scope 推定に依らず実体で判定する (Codex P2)。

        legacy 低 ID の user タグは base タグと tag_id を共有し得るため、``get_tag_scope`` の
        scope 推定 (衝突時 user 優先) では base 由来行を user と誤判定する。overlay が同一の
        ``(tag_id, tag)`` を実際に保持しているかで由来を判定することで、ID 衝突に依存しない。

        Args:
            row: 判定対象の TagSearchRow。

        Returns:
            overlay が同一 tag_id で同一 canonical タグ文字列を保持していれば ``True``。
        """
        if not self._has_user():
            return False
        assert self.user_repo is not None
        user_tag = self.user_repo.get_tag_by_id(row["tag_id"])
        return user_tag is not None and user_tag.tag == row["tag"]

    def _dedup_case_variant_user_rows(self, rows: list[TagSearchRow]) -> list[TagSearchRow]:
        """user overlay タグが base タグの大文字小文字違い重複なら結果から落とす (#1223)。

        user が独自登録した case-variant 重複 (例: base ``anime`` に対する user ``Anime``) は
        merge 時に base canonical を覆い隠し、手動タグ追加 (``resolve_preferred=True``) の
        exact 検索が既存 base タグへ解決できず重複を再生産する。別 tag_id の base に casefold
        一致する canonical タグがある overlay 由来行を落とし、呼び出し側 (LoRAIro の 3 段
        フォールバック等) が base canonical を解決できるようにする。

        - 由来判定は数値 ID scope 推定でなく overlay の実体 (``_is_overlay_origin_row``) で行う
          ため、legacy 低 ID の user タグと base タグの ID 衝突で base 行を誤って落とさない
          (Codex P2)。
        - 別文字列の user alias (typo 補正 #1183) は casefold が一致しないため触れない。
        - base タグの deprecated 有無は判定に用いない (#1212: deprecated と case 重複は別軸)。
        - ``resolve_preferred=True`` の解決経路でのみ呼ばれる (ブラウズ検索は user 行をそのまま
          表示する)。

        Args:
            rows: cross-scope preferred 解決済みの TagSearchRow リスト。

        Returns:
            case-variant な overlay 重複を除いた TagSearchRow リスト。
        """
        if not self._has_user() or not rows:
            return rows
        kept: list[TagSearchRow] = []
        for row in rows:
            if self._is_overlay_origin_row(row) and self._base_has_case_variant(
                row["tag"], exclude_tag_id=row["tag_id"]
            ):
                continue
            kept.append(row)
        return kept

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, TagSearchRow]:
        merged: dict[str, TagSearchRow] = self._merge_by_key(
            "search_tags_bulk",
            None,
            keywords,
            format_name=format_name,
            resolve_preferred=False,
        )
        if merged:
            requested_format_id = self._requested_format_id(format_name)
            patched = self._apply_user_patches_to_search_rows(
                list(merged.values()),
                requested_format_id=requested_format_id,
            )
            patched_by_tag_id = {row["tag_id"]: row for row in patched}
            merged = {keyword: patched_by_tag_id.get(row["tag_id"], row) for keyword, row in merged.items()}
            # tombstone で選ばれた行の一致訳が消えた keyword は、次候補を per-keyword
            # search で引き直す (別 tag が同じ訳で一致し得るため、単に落とすと
            # search_tags / search_tags_bulk_all と結果が食い違う。#121 Codex P2)
            dropped = [
                keyword
                for keyword, row in merged.items()
                if not self._row_still_matches_keyword(row, keyword)
            ]
            for keyword in dropped:
                fallback_rows = self.search_tags(
                    keyword, partial=False, format_name=format_name, resolve_preferred=False
                )
                if fallback_rows:
                    merged[keyword] = fallback_rows[0]
                else:
                    del merged[keyword]
        if not resolve_preferred:
            return merged
        merged = {keyword: self._resolve_cross_scope_preferred([row])[0] for keyword, row in merged.items()}
        # OverlayTagReader.search_tags_bulk がスタブのため、未解決キーワードを
        # 個別 search_tags で補完する (cross-scope preferred 解決を含む)
        missing = [kw for kw in keywords if kw not in merged]
        for kw in missing:
            rows = self.search_tags(kw, partial=False, format_name=format_name, resolve_preferred=True)
            if rows:
                merged[kw] = rows[0]
        return merged

    def search_tags_bulk_all(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, list[TagSearchRow]]:
        """`search_tags_bulk` の全マッチ行版をマージして返す (#998)。

        `_merge_search_tags_adaptive` (= `search_tags`) の batch 版。base repos を low->high、
        続けて `user_repo` の順に各 `search_tags_bulk_all` を呼び、keyword ごとに tag_id -> row
        の dict で結合する (後勝ち: 高優先度 base → user_repo が最優先。`_merge_by_key` /
        `search_tags` と同じ意味論、Codex PR #115 P2)。これにより:

        - 複数 base DB で同一 tag_id が重複しても高優先度 DB の行を採用する。
        - user-only タグ / user 翻訳パッチ / user-only reader (Overlay を base とする構成) の
          行も `search_tags` と同じく取りこぼさない。

        大 base DB は `TagReader.search_tags_bulk_all` が SQL レベルで batch するため N+1 は
        起きない (user overlay は小さいので `OverlayTagReader.search_tags_bulk_all` の
        per-keyword ループで実用上問題ない)。結合後、user patch (翻訳 / status / usage) を全行へ
        `_apply_user_patches_to_search_rows` で一括適用し、`resolve_preferred=True` なら
        cross-scope preferred を解決する。
        """
        # base low->high の後に user_repo。keyword ごとに tag_id -> row (後勝ち = 高優先度が勝つ)。
        repos: list[TagReader | OverlayTagReader] = [*self._iter_base_repos_low_to_high()]
        if self._has_user():
            assert self.user_repo is not None
            repos.append(self.user_repo)

        merged_by_keyword: dict[str, dict[int, TagSearchRow]] = {}
        for repo in repos:
            result = repo.search_tags_bulk_all(
                keywords,
                format_name=format_name,
                resolve_preferred=False,
            )
            for keyword, rows in result.items():
                bucket = merged_by_keyword.setdefault(keyword, {})
                for row in rows:
                    bucket[row["tag_id"]] = row
        # tag_id 昇順で返す (`_merge_search_tags_adaptive` / `TagReader.search_tags_bulk_all` と
        # 同じ決定的順序。batch へ切替えても per-query search と行順が一致する、Codex PR #115 P3)。
        merged: dict[str, list[TagSearchRow]] = {
            keyword: [rows[tag_id] for tag_id in sorted(rows)]
            for keyword, rows in merged_by_keyword.items()
        }

        if merged:
            requested_format_id = self._requested_format_id(format_name)
            all_rows = [row for rows in merged.values() for row in rows]
            patched = self._apply_user_patches_to_search_rows(
                all_rows,
                requested_format_id=requested_format_id,
            )
            patched_by_tag_id = {row["tag_id"]: row for row in patched}
            merged = {
                keyword: [patched_by_tag_id.get(row["tag_id"], row) for row in rows]
                for keyword, rows in merged.items()
            }
            # tombstone で唯一の一致訳が消えた row を落とし、空になった keyword は除く (#121 Codex P2)
            merged = {
                keyword: kept
                for keyword, rows in merged.items()
                if (kept := [row for row in rows if self._row_still_matches_keyword(row, keyword)])
            }

        if resolve_preferred:
            merged = {
                keyword: self._resolve_cross_scope_preferred(rows) for keyword, rows in merged.items()
            }

        return merged

    def get_format_map(self) -> dict[int, str]:
        return self._merge_by_key("get_format_map", None)

    def get_type_mapping_map(self) -> dict[tuple[int, int], str]:
        return self._merge_by_key("get_type_mapping_map", None)

    # ------------------------------------------------------------------
    # Pattern C: _accumulate_unique (全リポから収集、タプルキーで重複排除)
    # ------------------------------------------------------------------

    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        # get_translations_batch と同じ収集順・除外規則で 1 tag ぶんを返す。
        # (batch 版へ委譲すると get_translations しか持たない duck-typed reader を壊す)
        hidden = self._translation_tombstones_batch([tag_id]).get(tag_id, set())
        base_hidden = self._hidden_pairs_for_scope(hidden, "base")
        user_hidden = self._hidden_pairs_for_scope(hidden, "user")
        seen: set[tuple[str | None, str | None]] = set()
        result: list[TagTranslation] = []
        for repo in self._iter_base_repos_low_to_high():
            self_filtering = getattr(repo, "get_translation_tombstones_batch", None) is not None
            for tr in repo.get_translations(tag_id):
                if not self_filtering and (tr.language, tr.translation) in base_hidden:
                    continue
                key = (tr.language, tr.translation)
                if key not in seen:
                    seen.add(key)
                    result.append(tr)
        if self._has_user():
            assert self.user_repo is not None
            self_filtering = getattr(self.user_repo, "get_translation_tombstones_batch", None) is not None
            for tr in self.user_repo.get_translations(tag_id):
                if not self_filtering and (tr.language, tr.translation) in user_hidden:
                    continue
                key = (tr.language, tr.translation)
                if key not in seen:
                    seen.add(key)
                    result.append(tr)
        return result

    def _translation_tombstones_batch(self, tag_ids: list[int]) -> dict[int, set[tuple[str, str, str]]]:
        """user overlay の翻訳 tombstone (#121) を取得する。

        tombstone を提供できる repo (base repos + user_repo) から集めて union する。
        どの repo も提供しない (legacy TagReader のみ等) 場合は空 dict を返す。

        Returns:
            ``{tag_id: {(target_scope, language, translation), ...}}``。scope を保持するのは
            legacy 低 id の user タグが base タグと数値 id を共有し得るため (Codex P2)。
        """
        # get_user_tag_reader() は OverlayTagReader を base_repo として単独ラップする
        # (user_repo=None) ため、user_repo だけを見ると user-only 読みで tombstone が
        # 空になる (Codex P2)。preference (#122) と同じく、tombstone を提供できる repo を
        # 優先度 低→高 の順に集めて union する。
        result: dict[int, set[tuple[str, str, str]]] = {}
        providers = [*self._iter_base_repos_low_to_high()]
        if self.user_repo is not None:
            providers.append(self.user_repo)
        for repo in providers:
            getter = getattr(repo, "get_translation_tombstones_batch", None)
            if getter is None:
                continue
            for tag_id, hidden in getter(tag_ids).items():
                result.setdefault(tag_id, set()).update(hidden)
        return result

    @staticmethod
    def _hidden_pairs_for_scope(hidden: set[tuple[str, str, str]], scope: str) -> set[tuple[str, str]]:
        """指定 scope 宛の tombstone を (language, translation) 集合に射影する。"""
        return {(language, translation) for s, language, translation in hidden if s == scope}

    def get_translations_batch(self, tag_ids: list[int]) -> dict[int, list[TagTranslation]]:
        """複数タグIDの翻訳を全リポジトリからバッチ取得してマージする。

        全リポジトリから一括取得し、(tag_id, language, translation) タプルで重複排除する。
        重複時は先着順（低優先度→高優先度→user_repo）で保持する。
        get_translations と同一のセマンティクスを保つ。
        tombstone (#121) 済みの (language, translation) は base 由来でも除外する。

        Args:
            tag_ids: 翻訳を取得するタグIDのリスト。空リストの場合は空辞書を返す。

        Returns:
            tag_id をキーとする重複排除済み TagTranslation リストの辞書。
        """
        if not tag_ids:
            return {}
        tombstoned = self._translation_tombstones_batch(tag_ids)
        seen: set[tuple[int, str | None, str | None]] = set()
        result: dict[int, list[TagTranslation]] = {}
        for repo in self._iter_base_repos_low_to_high():
            # 自前で scope-aware に除外する reader (OverlayTagReader) は素通しし、
            # 素の base reader の行だけ base 宛 tombstone で除外する (Codex P2: scope 保持)
            self_filtering = getattr(repo, "get_translation_tombstones_batch", None) is not None
            for tag_id, trs in repo.get_translations_batch(tag_ids).items():
                base_hidden = self._hidden_pairs_for_scope(tombstoned.get(tag_id, set()), "base")
                for tr in trs:
                    if not self_filtering and (tr.language, tr.translation) in base_hidden:
                        continue
                    key = (tr.tag_id, tr.language, tr.translation)
                    if key not in seen:
                        seen.add(key)
                        result.setdefault(tag_id, []).append(tr)
        if self._has_user():
            assert self.user_repo is not None
            self_filtering = getattr(self.user_repo, "get_translation_tombstones_batch", None) is not None
            for tag_id, trs in self.user_repo.get_translations_batch(tag_ids).items():
                user_hidden = self._hidden_pairs_for_scope(tombstoned.get(tag_id, set()), "user")
                for tr in trs:
                    if not self_filtering and (tr.language, tr.translation) in user_hidden:
                        continue
                    key = (tr.tag_id, tr.language, tr.translation)
                    if key not in seen:
                        seen.add(key)
                        result.setdefault(tag_id, []).append(tr)
        return result

    def get_usage_counts_batch(self, tag_ids: list[int]) -> dict[int, dict[int, int]]:
        """複数タグIDの format 別使用回数を全リポジトリからバッチ取得してマージする。

        base_repos (低優先度→高優先度) → user_repo の順に ``(tag_id, format_id)``
        単位で上書きマージする。user_repo の patch が最優先となり、単一取得の
        :meth:`get_usage_count` (``_first_found``: user 優先) と同じセマンティクスを保つ。

        Args:
            tag_ids: 使用回数を取得するタグIDのリスト。空リストの場合は空辞書を返す。

        Returns:
            tag_id をキーとする ``{format_id: count}`` 辞書のネスト辞書。
        """
        if not tag_ids:
            return {}
        result: dict[int, dict[int, int]] = {}
        for repo in self._iter_base_repos_low_to_high():
            for tag_id, counts in repo.get_usage_counts_batch(tag_ids).items():
                result.setdefault(tag_id, {}).update(counts)
        if self._has_user():
            assert self.user_repo is not None
            for tag_id, counts in self.user_repo.get_usage_counts_batch(tag_ids).items():
                result.setdefault(tag_id, {}).update(counts)
        return result

    def list_translations(self) -> list[TagTranslation]:
        # 列挙経路にも get_translations* と同じ tombstone 除外規則を適用する (#121 Codex P2)。
        # 自前で scope-aware に除外する reader (OverlayTagReader) は素通しし、素の base
        # reader の行だけ base 宛 tombstone で除外する。
        repo_entries: list[tuple[Any, str]] = [
            (repo, "base") for repo in self._iter_base_repos_low_to_high()
        ]
        if self._has_user():
            assert self.user_repo is not None
            repo_entries.append((self.user_repo, "user"))
        seen: set[tuple[int | None, str | None, str | None]] = set()
        result: list[TagTranslation] = []
        for repo, scope in repo_entries:
            rows = repo.list_translations()
            self_filtering = getattr(repo, "get_translation_tombstones_batch", None) is not None
            hidden_map: dict[int, set[tuple[str, str, str]]] = {}
            if not self_filtering and rows:
                tag_ids = sorted({tr.tag_id for tr in rows if tr.tag_id is not None})
                hidden_map = self._translation_tombstones_batch(tag_ids)
            for tr in rows:
                if not self_filtering:
                    hidden = self._hidden_pairs_for_scope(hidden_map.get(tr.tag_id, set()), scope)
                    if (tr.language, tr.translation) in hidden:
                        continue
                key = (tr.tag_id, tr.language, tr.translation)
                if key not in seen:
                    seen.add(key)
                    result.append(tr)
        return result

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
    from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
    from genai_tag_db_tools.db.runtime import (
        get_base_session_factories,
        get_user_session_factory_optional,
    )

    user_factory = get_user_session_factory_optional()
    user_repo = OverlayTagReader(session_factory=user_factory) if user_factory else None

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
