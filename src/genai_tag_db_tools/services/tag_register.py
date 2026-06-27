import logging
from typing import TYPE_CHECKING

import polars as pl

from genai_tag_db_tools.db.repository import (
    TagRepository,
    get_default_reader,
    get_default_repository,
)
from genai_tag_db_tools.db.schema import USER_TAG_ID_OFFSET
from genai_tag_db_tools.utils.cleanup_str import TagCleaner

if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.db.user_tag_repository import UserTagRepository
    from genai_tag_db_tools.models import (
        AliasRegisterInput,
        AliasRegisterItemResult,
        TagRegisterRequest,
        TagRegisterResult,
    )


class TagRegister:
    """タグの登録・更新を行うサービス。"""

    def __init__(self, repository: TagRepository | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else get_default_repository()

    def normalize_tags(self, df: pl.DataFrame) -> pl.DataFrame:
        """source_tag/tag を正規化して欠損を補完する。"""
        if "source_tag" not in df.columns or "tag" not in df.columns:
            return df

        df = df.with_columns(
            pl.when(pl.col("source_tag") == "")
            .then(pl.col("tag"))
            .otherwise(pl.col("source_tag"))
            .alias("source_tag")
        )

        df = df.with_columns(
            pl.when(pl.col("tag") == "")
            .then(pl.col("source_tag").map_elements(TagCleaner.clean_format))
            .otherwise(pl.col("tag"))
            .alias("tag")
        )
        return df

    def insert_tags_and_attach_id(self, df: pl.DataFrame) -> pl.DataFrame:
        """タグを一括登録し、tag_id を付与する。"""
        if "tag" not in df.columns:
            return df

        self._repo.bulk_insert_tags(df.select(["source_tag", "tag"]))

        unique_tags = df["tag"].unique().to_list()
        existing_map = self._repo._fetch_existing_tags_as_map(unique_tags)

        df = df.with_columns(
            pl.col("tag")
            .map_elements(lambda t: existing_map.get(t, None), return_dtype=pl.Int64)
            .alias("tag_id")
        )
        return df

    def update_usage_counts(self, df: pl.DataFrame, format_id: int) -> None:
        """usage_count を登録・更新する。"""
        if "tag_id" not in df.columns or "count" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            usage_count = row["count"]
            if tag_id is not None and usage_count is not None:
                self._repo.update_usage_count(tag_id, format_id, usage_count)

    def update_translations(self, df: pl.DataFrame, language: str) -> None:
        """翻訳を登録・更新する。"""
        if "tag_id" not in df.columns or "translation" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            trans = row["translation"]
            if tag_id is not None and trans:
                self._repo.add_or_update_translation(tag_id, language, trans)

    def update_deprecated_tags(self, df: pl.DataFrame, format_id: int) -> None:
        """deprecated_tags を alias として登録する。"""
        if "tag_id" not in df.columns or "deprecated_tags" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            dep_str = row.get("deprecated_tags", "")
            if not dep_str:
                continue

            for dep_tag_raw in dep_str.split(","):
                dep_tag = TagCleaner.clean_format(dep_tag_raw)
                if not dep_tag:
                    continue

                alias_tag_id = self._repo.create_tag(dep_tag, dep_tag)
                self._repo.update_tag_status(
                    tag_id=alias_tag_id,
                    format_id=format_id,
                    alias=True,
                    preferred_tag_id=tag_id,
                )


class TagRegisterService:
    """Qt-free tag registration service for CLI/library/GUI use."""

    def __init__(
        self,
        repository: TagRepository | None = None,
        reader: "MergedTagReader | None" = None,
        user_tag_repo: "UserTagRepository | None" = None,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else get_default_repository()
        self._reader = reader or get_default_reader()
        if user_tag_repo is not None:
            self._user_tag_repo: "UserTagRepository | None" = user_tag_repo
        else:
            from genai_tag_db_tools.db.runtime import get_user_session_factory_optional
            from genai_tag_db_tools.db.user_tag_repository import UserTagRepository as _UserTagRepository

            user_factory = get_user_session_factory_optional()
            self._user_tag_repo = _UserTagRepository(user_factory) if user_factory else None

    def _resolve_format_id(self, format_name: str) -> int:
        """フォーマット名からformat_idを解決する。存在しない場合は自動作成。

        Args:
            format_name: フォーマット名。

        Returns:
            解決されたformat_id。
        """
        try:
            return self._reader.get_format_id(format_name)
        except ValueError:
            fmt_id = self._repo.create_format_if_not_exists(
                format_name=format_name,
                description=f"Auto-created format: {format_name}",
                reader=self._reader,
            )
            self.logger.info(f"Auto-created format_name: {format_name} (ID: {fmt_id})")
            return fmt_id

    def _resolve_type_id(self, type_name: str, format_name: str, fmt_id: int) -> int:
        """タイプ名からformat固有のtype_idを解決する。

        2段階で解決する:
        1) type_name → type_name_id（TAG_TYPE_NAME）
        2) (type_name, format_id) → type_id（TAG_TYPE_FORMAT_MAPPING）

        マッピングが存在しない場合は自動作成する。
        unknownはtype_id=0固定、それ以外はget_next_type_idで採番する。

        Args:
            type_name: タイプ名。
            format_name: フォーマット名（ログ用）。
            fmt_id: フォーマットID。

        Returns:
            解決されたformat固有のtype_id。
        """
        # Stage 1: type_name_id を確保
        type_name_id = self._repo.create_type_name_if_not_exists(
            type_name=type_name, description=f"Auto-created type: {type_name}"
        )

        # Stage 2: format固有の type_id を解決
        type_id = self._reader.get_type_id_for_format(type_name, fmt_id)

        if type_id is not None:
            # type_id/type_name 不整合検知
            if type_name == "unknown" and type_id != 0:
                self.logger.warning(
                    f"type_id/type_name mismatch: type_name='unknown' but type_id={type_id} "
                    f"(expected 0) in format '{format_name}'"
                )
            elif type_name != "unknown" and type_id == 0:
                self.logger.warning(
                    f"type_id/type_name mismatch: type_name='{type_name}' resolved to type_id=0 "
                    f"(reserved for 'unknown') in format '{format_name}'"
                )
            return type_id

        # マッピング未存在: 新規作成
        if type_name == "unknown":
            new_type_id = 0
        else:
            new_type_id = self._repo.get_next_type_id(fmt_id)
            # type_id=0はunknown専用として予約
            if new_type_id == 0:
                new_type_id = 1

        resolved_type_id = self._repo.create_type_format_mapping_if_not_exists(
            format_id=fmt_id,
            type_id=new_type_id,
            type_name_id=type_name_id,
            description=f"Auto-created mapping for {format_name}/{type_name}",
        )
        self.logger.info(
            f"Auto-created type_name: {type_name} for format {format_name} (type_id: {resolved_type_id})"
        )
        return resolved_type_id

    def register_tag(self, request: "TagRegisterRequest") -> "TagRegisterResult":
        """Register a tag and optional metadata via the repository.

        Automatically creates format_name and type_name if they don't exist.
        For unknown type_name, uses type_id=0 by default.
        scope="user" のとき overlay path (USER_TAGS / USER_TAG_STATUS_PATCH) に書く。

        Args:
            request: Tag registration request.
        Returns:
            TagRegisterResult indicating whether the tag was created.
        """
        if request.scope == "user":
            return self._register_user_tag(request)

        from genai_tag_db_tools.models import TagRegisterResult

        tag = request.tag
        source_tag = request.source_tag or request.tag

        fmt_id = self._resolve_format_id(request.format_name)

        type_name = request.type_name or "unknown"
        type_id = self._resolve_type_id(type_name, request.format_name, fmt_id)

        existing_id = self._reader.get_tag_id_by_name(tag, partial=False)
        tag_id = self._repo.create_tag(source_tag, tag)
        created = existing_id is None

        preferred_tag_id: int | None = tag_id
        if request.alias:
            if not request.preferred_tag:
                raise ValueError("alias=True の場合 preferred_tag が必須です")
            preferred_tag_id = self._reader.get_tag_id_by_name(request.preferred_tag, partial=False)
            if preferred_tag_id is None:
                raise ValueError(f"推奨タグが見つかりません: {request.preferred_tag}")

        if request.translations:
            for tr in request.translations:
                self._repo.add_or_update_translation(tag_id, tr.language, tr.translation)

        if preferred_tag_id is None:
            raise ValueError("preferred_tag_id が未設定です")

        self._repo.update_tag_status(
            tag_id=tag_id,
            format_id=fmt_id,
            alias=request.alias,
            preferred_tag_id=preferred_tag_id,
            type_id=type_id,
        )

        return TagRegisterResult(created=created, tag_id=tag_id)

    def _register_user_tag(self, request: "TagRegisterRequest") -> "TagRegisterResult":
        """USER_TAGS / USER_TAG_STATUS_PATCH にタグを登録する。

        Args:
            request: scope="user" のタグ登録リクエスト。

        Returns:
            TagRegisterResult indicating whether the tag was created.

        Raises:
            RuntimeError: user DB が未初期化の場合。
            ValueError: alias=True なのに preferred_tag が未指定/未存在の場合。
        """
        from genai_tag_db_tools.models import TagRegisterResult

        if self._user_tag_repo is None:
            raise RuntimeError("User DB が未初期化です。init_user_db() を先に呼んでください。")

        tag = request.tag
        source_tag = request.source_tag or request.tag

        fmt_id = self._resolve_format_id(request.format_name)
        type_name = request.type_name or "unknown"
        type_id = self._resolve_type_id(type_name, request.format_name, fmt_id)

        existing_id = self._reader.get_tag_id_by_name(tag, partial=False)
        tag_id = self._user_tag_repo.create_user_tag(source_tag, tag)
        created = existing_id is None

        if request.alias:
            if not request.preferred_tag:
                raise ValueError("alias=True の場合 preferred_tag が必須です")
            preferred_tag_id = self._reader.get_tag_id_by_name(request.preferred_tag, partial=False)
            if preferred_tag_id is None:
                raise ValueError(f"推奨タグが見つかりません: {request.preferred_tag}")
            preferred_scope = "base" if preferred_tag_id < USER_TAG_ID_OFFSET else "user"
        else:
            preferred_tag_id = tag_id
            preferred_scope = "user"

        self._user_tag_repo.write_patch(
            target_scope="user",
            target_tag_id=tag_id,
            format_id=fmt_id,
            type_id=type_id,
            alias=request.alias,
            preferred_scope=preferred_scope,
            preferred_tag_id=preferred_tag_id,
        )

        return TagRegisterResult(created=created, tag_id=tag_id)

    def register_alias_entry(
        self,
        entry: "AliasRegisterInput",
        dry_run: bool,
    ) -> "AliasRegisterItemResult":
        """alias 1エントリを user DB に登録する（または dry-run で確認する）。

        Args:
            entry: 登録対象のaliasエントリ。
            dry_run: Trueの場合はDB変更を行わず would_create を返す。

        Returns:
            AliasRegisterItemResult: 処理結果。
        """
        from genai_tag_db_tools.models import AliasRegisterItemResult

        # 1. preferred タグを lookup
        preferred_tag_id = self._reader.get_tag_id_by_name(entry.preferred, partial=False)
        if preferred_tag_id is None:
            return AliasRegisterItemResult(
                alias=entry.alias,
                preferred=entry.preferred,
                status="missing_preferred",
            )

        # 2. format / type を解決
        fmt_id = self._resolve_format_id(entry.format_name)
        type_id = self._resolve_type_id(entry.type_name, entry.format_name, fmt_id)

        # 3. alias タグの既存チェック
        alias_tag_id = self._reader.get_tag_id_by_name(entry.alias, partial=False)
        if alias_tag_id is not None:
            status = self._reader.get_tag_status(alias_tag_id, fmt_id)
            if status is not None and status.alias:
                if status.preferred_tag_id == preferred_tag_id:
                    return AliasRegisterItemResult(
                        alias=entry.alias,
                        preferred=entry.preferred,
                        status="skipped",
                        alias_tag_id=alias_tag_id,
                        preferred_tag_id=preferred_tag_id,
                    )
                return AliasRegisterItemResult(
                    alias=entry.alias,
                    preferred=entry.preferred,
                    status="conflict",
                    alias_tag_id=alias_tag_id,
                    preferred_tag_id=preferred_tag_id,
                )

        # 4. dry_run モード: DB 変更なし
        if dry_run:
            return AliasRegisterItemResult(
                alias=entry.alias,
                preferred=entry.preferred,
                status="would_create",
                preferred_tag_id=preferred_tag_id,
            )

        # 5. 実際に作成
        new_alias_tag_id = self._repo.create_tag(entry.alias, entry.alias)
        self._repo.update_tag_status(
            tag_id=new_alias_tag_id,
            format_id=fmt_id,
            alias=True,
            preferred_tag_id=preferred_tag_id,
            type_id=type_id,
        )
        return AliasRegisterItemResult(
            alias=entry.alias,
            preferred=entry.preferred,
            status="created",
            alias_tag_id=new_alias_tag_id,
            preferred_tag_id=preferred_tag_id,
        )
