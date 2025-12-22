import logging

import polars as pl

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.utils.cleanup_str import TagCleaner


class TagRegister:
    """タグの登録・更新を行うサービス。"""

    def __init__(self, repository: TagRepository | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else TagRepository()

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
