import logging
from typing import TYPE_CHECKING

import polars as pl

from genai_tag_db_tools.db.repository import (
    TagRepository,
    get_default_reader,
    get_default_repository,
)
from genai_tag_db_tools.utils.cleanup_str import TagCleaner

if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult


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
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else get_default_repository()
        self._reader = reader or get_default_reader()

    def register_tag(self, request: "TagRegisterRequest") -> "TagRegisterResult":
        """Register a tag and optional metadata via the repository.

        Automatically creates format_name and type_name if they don't exist.
        For unknown type_name, uses type_id=0 by default.

        Args:
            request: Tag registration request.
        Returns:
            TagRegisterResult indicating whether the tag was created.
        """
        from genai_tag_db_tools.models import TagRegisterResult

        tag = request.tag
        source_tag = request.source_tag or request.tag

        # Auto-create format if it doesn't exist
        try:
            fmt_id = self._reader.get_format_id(request.format_name)
        except ValueError:
            # Format doesn't exist, create it
            # Pass reader to avoid format_id collision with base DBs
            fmt_id = self._repo.create_format_if_not_exists(
                format_name=request.format_name,
                description=f"Auto-created format: {request.format_name}",
                reader=self._reader,
            )
            self.logger.info(f"Auto-created format_name: {request.format_name} (ID: {fmt_id})")

        # Auto-create type_name if it doesn't exist
        type_name = request.type_name or "unknown"
        type_id_result = self._reader.get_type_id(type_name)
        if type_id_result is None:
            # Type doesn't exist, create it
            # First, ensure the type_name exists in TAG_TYPE_NAME table
            type_name_id = self._repo.create_type_name_if_not_exists(
                type_name=type_name, description=f"Auto-created type: {type_name}"
            )

            # Create the mapping (format_id + type_id + type_name_id)
            # Use type_id=0 for the default unknown type in this format
            type_id = 0
            self._repo.create_type_format_mapping_if_not_exists(
                format_id=fmt_id,
                type_id=type_id,
                type_name_id=type_name_id,
                description=f"Auto-created mapping for {request.format_name}/{type_name}",
            )
            self.logger.info(
                f"Auto-created type_name: {type_name} for format {request.format_name} (type_id: {type_id})"
            )
        else:
            type_id = type_id_result

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
