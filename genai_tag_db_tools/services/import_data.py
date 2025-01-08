# genai_tag_db_tools.services.import_data
import logging
from pathlib import Path
from typing import Optional

import polars as pl
from PySide6.QtCore import QObject, Signal
from dataclasses import dataclass, field

# DBアクセスまわり（TagRepositoryのみを利用）
from genai_tag_db_tools.data.tag_repository import TagRepository
from genai_tag_db_tools.db.database_setup import engine, db_path

# ユーティリティ
from genai_tag_db_tools.utils.cleanup_str import TagCleaner
from genai_tag_db_tools.services.polars_schema import AVAILABLE_COLUMNS

logger = logging.getLogger(__name__)


@dataclass
class ImportConfig:
    """
    インポート時に必要な設定をまとめたデータクラス
    - フォーマットID
    - 言語 (翻訳を登録する際の言語コード)
    - データフレーム上で有効なカラム名リスト
    """
    format_id: int = 0  # 0 = Unknown, 1 = danbooru, etc.
    language: Optional[str] = None
    column_names: list[str] = field(default_factory=list)


class TagDataImporter(QObject):
    """
    タグデータのインポートを行うクラス。
    PySide6 のシグナルを用いてGUIに進捗や完了を通知可能。

    テストコードではGUI連携なしでも使えるよう、ロジック部分は
    publicメソッド or privateメソッドとして分割。
    """

    # --- PySide6 Signals (GUIから進捗確認する際に使用) ---
    process_started = Signal(str)         # 処理開始 ("インポート開始"など)
    progress_updated = Signal(int, str)   # 進捗度, メッセージ
    process_finished = Signal(str)        # 処理完了 ("インポート完了"など)
    error_occurred = Signal(str)          # エラーメッセージ

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # DB設定
        self._conn_path = db_path  # 必要なら外部から注入できるようにしても良い
        self._engine = engine

        # TagRepository のインスタンス化のみ
        self._tag_repo = TagRepository()

        # ユーザーによるキャンセルフラグ
        self._cancel_flag = False

    # ----------------------------------------------------------------------
    #  1) CSV / Parquet 読み込み
    # ----------------------------------------------------------------------
    def read_csv(self, csv_file_path: Path, has_header: bool = True) -> pl.DataFrame:
        """
        CSVファイルを読み込み、Polars DataFrameを返す。
        テスト時にはダミーファイルを用意し、read_csv が正しく動くか確認する。

        Args:
            csv_file_path (Path): CSVファイルパス
            has_header (bool): CSVにヘッダ行があるかどうか

        Returns:
            pl.DataFrame
        """
        logger.info(f"CSVファイルを読み込んでいます: {csv_file_path}")
        try:
            df = pl.read_csv(csv_file_path, has_header=has_header, encoding="utf-8")
            return df
        except Exception as e:
            logger.error(f"CSV読み込み中にエラー: {e}")
            raise

    def decide_csv_header(self, csv_file_path: Path) -> bool:
        """
        CSVファイルを事前に1行だけ読んで、AVAILABLE_COLUMNS に該当しそうな
        カラムがあれば has_header=True とみなす。

        Args:
            csv_file_path (Path)

        Returns:
            bool: True = ヘッダ有, False = ヘッダ無
        """
        try:
            with open(csv_file_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if any(col in first_line for col in AVAILABLE_COLUMNS):
                    return True
            return False
        except Exception as e:
            logger.warning(f"CSVファイル先頭チェック中にエラー: {e}")
            return True  # デフォルト True

    def load_hf_dataset(self, repository: str) -> pl.DataFrame:
        """
        Hugging Face DatasetなどをParquet形式で読み込む場合のメソッド。

        Args:
            repository (str): 例: "https://huggingface.co/.../data.parquet"

        Returns:
            pl.DataFrame
        """
        logger.info(f"Hugging Face Datasetを読み込み: {repository}")
        try:
            return pl.read_parquet(repository)
        except Exception as e:
            logger.error(f"Parquet読み込み中にエラー: {e}")
            raise

    # ----------------------------------------------------------------------
    #  2) インポート前のDataFrame加工/設定
    # ----------------------------------------------------------------------
    def configure_import(
        self,
        source_df: pl.DataFrame,
        format_id: int = 0,
        language: Optional[str] = None
    ) -> tuple[pl.DataFrame, ImportConfig]:
        """
        インポート用の設定やカラム名の整合性を確認し、最終的に
        - DataFrame
        - ImportConfig
        を組み立てて返す。
        テスト時には format_id, language を直接指定して呼び出す想定。

        Args:
            source_df (pl.DataFrame)
            format_id (int): フォーマットID (0=unknown, 1=danbooru, etc.)
            language (Optional[str]): 翻訳登録時の言語コード。無ければNone。

        Returns:
            (pl.DataFrame, ImportConfig)
        """
        logger.info(f"元データのカラム: {list(source_df.columns)}")

        # カラム正規化 (必要なら rename, drop, add など)
        # ここでは例として「source_tag」「tag」が存在しなければ補完する程度。
        # 実装はプロジェクト要件に応じて調整
        processed_df = self._ensure_minimum_columns(source_df)

        # カラム型の正規化
        processed_df = self._normalize_typing(processed_df)

        # インポート設定
        # → 必要に応じて利用側(CLI/GUI)でユーザー入力させたり、
        #   テストでは固定値を入れたりする。
        config = ImportConfig(
            format_id=format_id,
            language=language,
            column_names=list(processed_df.columns)
        )
        return processed_df, config

    def _ensure_minimum_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        「source_tag」や「tag」など最低限必要なカラムがあるか確認。
        ない場合は空文字列のカラムを追加するなど、テスト時にも
        不足カラムがあっても落ちないように工夫。

        Returns:
            pl.DataFrame
        """
        needed_cols = ["source_tag", "tag"]
        current_cols = df.columns

        for col in needed_cols:
            if col not in current_cols:
                df = df.with_columns(pl.lit("").alias(col))

        return df

    def _normalize_typing(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        DataFrameの各カラムを想定する型に変換する。
        例: count が int である必要がある場合は int にキャストなど。

        Returns:
            pl.DataFrame
        """
        # AVAILABLE_COLUMNS参照して型変換してもよいが、ここでは簡易例
        if "count" in df.columns:
            df = df.with_columns(pl.col("count").cast(pl.Int64))
        return df

    # ----------------------------------------------------------------------
    #  3) インポート実行
    # ----------------------------------------------------------------------
    def import_data(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """
        メインのインポート処理。
        - タグ正規化
        - タグ登録(tag_id付与)
        - usage_counts 登録
        - 翻訳 (language, translation) 登録
        - deprecated_tags (エイリアス) 管理
        などの処理を行う。

        テストでは DataFrame と ImportConfig を作って呼び出し、
        DBに正しいレコードが登録されるか確認できる。

        Args:
            df (pl.DataFrame)
            config (ImportConfig)
        """
        self.process_started.emit("インポート開始")
        logger.info("インポート開始")

        if self._cancel_flag:
            logger.info("キャンセルフラグが立っています。処理を中断します。")
            return

        try:
            # 1) タグを正規化 (source_tag → tag)
            normalized_df = self._normalize_tags(df)

            # 2) タグ登録 (bulk_insert_tags → 既存 + 新規タグID取得) → tag_idカラム付与
            enriched_df = self._insert_tags_and_attach_id(normalized_df)

            # 3) Usage Count の登録
            if "count" in enriched_df.columns:
                self._update_usage_counts(enriched_df, config.format_id)

            # 4) 翻訳登録
            if config.language and "translation" in enriched_df.columns:
                self._update_translations(enriched_df, config.language)

            # 5) deprecated_tags (alias=True) の処理
            if "deprecated_tags" in enriched_df.columns:
                self._update_deprecated_tags(enriched_df, config.format_id)

            self.process_finished.emit("インポート完了")
            logger.info("インポート完了")
        except Exception as e:
            logger.error(f"インポート中にエラーが発生: {e}")
            self.error_occurred.emit(str(e))
            raise

    def _normalize_tags(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        - source_tag が空なら tag をコピー
        - tag が空なら source_tag をTagCleaner.clean_formatでクリーニングしてtagにコピー

        Returns:
            pl.DataFrame
        """
        if "source_tag" not in df.columns or "tag" not in df.columns:
            return df  # 必須列がなければ何もしない

        # source_tag が空なら tag をコピー
        df = df.with_columns(
            pl.when(pl.col("source_tag") == "")
            .then(pl.col("tag"))
            .otherwise(pl.col("source_tag"))
            .alias("source_tag")
        )

        # tag が空なら source_tag をクリーニングしてコピー
        df = df.with_columns(
            pl.when(pl.col("tag") == "")
            .then(pl.col("source_tag").map_elements(TagCleaner.clean_format))
            .otherwise(pl.col("tag"))
            .alias("tag")
        )
        return df

    def _insert_tags_and_attach_id(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        タグ名からDBに登録し、tag_idを取得してDataFrameに付与する。

        Returns:
            pl.DataFrame: tag_idカラムが追加されたDF
        """
        if "tag" not in df.columns:
            return df

        # 1) 新規タグを一括登録 (既存のものはスキップされる)
        self._tag_repo.bulk_insert_tags(df.select(["source_tag", "tag"]))

        # 2) DB上にあるタグ → tag_id をまとめて取得
        unique_tags = df["tag"].unique().to_list()
        tag_map = self._tag_repo._fetch_existing_tags_as_map(unique_tags)

        # 3) tag → tag_id へ置換
        df = df.with_columns(
            pl.col("tag")
            .map_elements(lambda t: tag_map.get(t, None), return_dtype=pl.Int64)
            .alias("tag_id")
        )
        return df

    def _update_usage_counts(self, df: pl.DataFrame, format_id: int) -> None:
        """
        count カラムを参照して TagUsageCounts に登録する。
        """
        if "tag_id" not in df.columns or "count" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            usage_count = row["count"]
            if tag_id is not None and usage_count is not None:
                self._tag_repo.update_usage_count(
                    tag_id=tag_id,
                    format_id=format_id,
                    count=usage_count
                )

    def _update_translations(self, df: pl.DataFrame, language: str) -> None:
        """
        'translation' カラムを参照して、TagTranslation に登録する。
        """
        if "tag_id" not in df.columns or "translation" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            trans = row["translation"]
            if tag_id is not None and trans:
                self._tag_repo.add_or_update_translation(tag_id, language, trans)

    def _update_deprecated_tags(self, df: pl.DataFrame, format_id: int) -> None:
        """
        'deprecated_tags' カラムを展開し、エイリアス(alias=True)として登録する。
        """
        if "tag_id" not in df.columns:
            return

        for row in df.iter_rows(named=True):
            tag_id = row["tag_id"]
            dep_str = row.get("deprecated_tags", "")
            if not dep_str:
                continue

            # カンマ区切りを分割 → クリーニング → alias登録
            for dep_tag_raw in dep_str.split(","):
                dep_tag = TagCleaner.clean_format(dep_tag_raw)
                if not dep_tag:
                    continue
                # alias 用に作成
                alias_tag_id = self._tag_repo.create_tag(dep_tag, dep_tag)
                # alias=True, preferred_tag_id=tag_id で status 登録
                self._tag_repo.update_tag_status(
                    tag_id=alias_tag_id,
                    format_id=format_id,
                    alias=True,
                    preferred_tag_id=tag_id
                )

    # ----------------------------------------------------------------------
    #  4) キャンセル / クリーンアップ
    # ----------------------------------------------------------------------
    def cancel(self):
        """
        外部から呼び出してフラグを立てると、インポート処理を中断できる。
        """
        logger.info("インポート処理のキャンセルが要求されました")
        self._cancel_flag = True

    def __del__(self):
        """
        クラス破棄時のクリーンアップ。
        以前は TagDatabase の cleanup() を呼んでいたが、Repository 側で都度
        セッションをクローズするため、特に何も行わない。
        """
        logger.debug("TagDataImporter のインスタンス破棄")
