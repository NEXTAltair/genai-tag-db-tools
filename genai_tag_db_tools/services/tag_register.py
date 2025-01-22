# genai_tag_db_tools/services/tag_register.py

import logging
from typing import Optional

import polars as pl

from genai_tag_db_tools.data.tag_repository import TagRepository
from genai_tag_db_tools.utils.cleanup_str import TagCleaner

class TagRegister:
    """
    DBへタグを登録・更新するためのビジネスロジックを集約したクラス。
    GUI依存は持たず、import_data など他のモジュールから利用される想定。
    """

    def __init__(self, repository: Optional[TagRepository] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else TagRepository()

    def normalize_tags(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        source_tag / tag カラムを補完・クリーニングする。
        - source_tag が空なら tag をコピー
        - tag が空なら source_tag をクリーニングしてコピー
        """
        if "source_tag" not in df.columns or "tag" not in df.columns:
            return df  # どちらか無ければ何もしない

        # source_tag が空 => tag をコピー
        df = df.with_columns(
            pl.when(pl.col("source_tag") == "")
            .then(pl.col("tag"))
            .otherwise(pl.col("source_tag"))
            .alias("source_tag")
        )

        # tag が空 => source_tag をクリーニングしてコピー
        df = df.with_columns(
            pl.when(pl.col("tag") == "")
            .then(pl.col("source_tag").map_elements(TagCleaner.clean_format))
            .otherwise(pl.col("tag"))
            .alias("tag")
        )
        return df

    def insert_tags_and_attach_id(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        タグを一括登録(bulk_insert_tags)して、tag_idカラムを付与したDataFrameを返す。
        """
        if "tag" not in df.columns:
            return df  # 必須カラム無ければ何もしない

        # 1) 新規タグだけ bulk insert (既存はスキップ)
        self._repo.bulk_insert_tags(df.select(["source_tag", "tag"]))

        # 2) DB上の (tag → tag_id) をマッピング取得
        unique_tags = df["tag"].unique().to_list()
        existing_map = self._repo._fetch_existing_tags_as_map(unique_tags)

        # 3) df の "tag" 列を "tag_id" に置き換え
        df = df.with_columns(
            pl.col("tag")
            .map_elements(lambda t: existing_map.get(t, None), return_dtype=pl.Int64)
            .alias("tag_id")
        )
        return df

    def update_usage_counts(self, df: pl.DataFrame, format_id: int) -> None:
        """
        count カラムを参照して usage_count を登録・更新。
        """
        if "tag_id" not in df.columns or "count" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            usage_count = row["count"]
            if tag_id is not None and usage_count is not None:
                self._repo.update_usage_count(
                    tag_id,
                    format_id,
                    usage_count
                )

    def update_translations(self, df: pl.DataFrame, language: str) -> None:
        """
        translation カラムを参照して翻訳を add_or_update_translation。
        """
        if "tag_id" not in df.columns or "translation" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            trans = row["translation"]
            if tag_id is not None and trans:
                self._repo.add_or_update_translation(
                    tag_id,
                    language,
                    trans
                )

    def update_deprecated_tags(self, df: pl.DataFrame, format_id: int) -> None:
        """
        deprecated_tags カラムにあるエイリアス情報を alias=True で登録する。
        """
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
                # alias用タグを登録
                alias_tag_id = self._repo.create_tag(dep_tag, dep_tag)
                # alias=True, preferred_tag_id=tag_id
                self._repo.update_tag_status(
                    tag_id=alias_tag_id,
                    format_id=format_id,
                    alias=True,
                    preferred_tag_id=tag_id
                )
