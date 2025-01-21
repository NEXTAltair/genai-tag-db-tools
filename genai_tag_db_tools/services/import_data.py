# genai_tag_db_tools/services/import_data.py

import logging
from pathlib import Path
from typing import Optional

import polars as pl
from PySide6.QtCore import QObject, Signal

# DBアクセスやタグ登録ロジックは、新規 tag_register.py の TagRegister に委譲
from genai_tag_db_tools.services.tag_register import TagRegister
from genai_tag_db_tools.db.database_setup import engine, db_path
from genai_tag_db_tools.services.polars_schema import AVAILABLE_COLUMNS


class ImportConfig:
    """
    インポート時に必要な設定をまとめたデータクラス (例)
    - format_id: DB登録時のフォーマットID
    - language: 翻訳登録に使う言語コード
    - column_names: 最終的に使用するDataFrameカラム名
    """
    def __init__(self, format_id: int = 0, language: Optional[str] = None, column_names: Optional[list[str]] = None):
        self.format_id = format_id
        self.language = language
        self.column_names = column_names or []


class TagDataImporter(QObject):
    """
    外部ファイル(CSV/Parquet等) を読み込み、DataFrameを前処理したあと、
    TagRegister を使ってDBに登録するクラス。

    ※ ここでは PySide6 のシグナルを使ってGUIに進捗やエラーを通知可能にしている。
    ※ 実際のGUIに組み込むかどうかは利用側で判断。
    """

    # --- PySide6 Signals ---
    process_started = Signal(str)         # 処理開始メッセージ ("インポート開始"など)
    progress_updated = Signal(int, str)   # (進捗度, メッセージ)
    process_finished = Signal(str)        # 処理完了メッセージ ("インポート完了"など)
    error_occurred = Signal(str)          # エラーメッセージ

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

        # DB関連設定 (必須なら外部から注入してもOK)
        self._conn_path = db_path
        self._engine = engine

        # タグ登録ロジックを委譲するサービス
        self._register_svc = TagRegister()

        # ユーザーによるキャンセルフラグ (必要に応じて使う)
        self._cancel_flag = False

    # ----------------------------------------------------------------------
    #  (1) CSV / Parquet ファイル読み込み
    # ----------------------------------------------------------------------
    def read_csv(self, csv_file_path: Path, has_header: bool = True) -> pl.DataFrame:
        """
        CSVファイルを読み込み、PolarsのDataFrameを返す。
        """
        self.logger.info(f"CSVファイルを読み込み: {csv_file_path}")
        try:
            df = pl.read_csv(csv_file_path, has_header=has_header, encoding="utf-8")
            return df
        except Exception as e:
            self.logger.error(f"CSV読み込み中にエラー: {e}")
            raise

    def decide_csv_header(self, csv_file_path: Path) -> bool:
        """
        CSVファイル先頭行を覗き見して、AVAILABLE_COLUMNS との一致度で
        ヘッダあり/なしをざっくり判定するサンプルロジック。
        """
        try:
            with open(csv_file_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if any(col in first_line for col in AVAILABLE_COLUMNS):
                    return True
            return False
        except Exception as e:
            self.logger.warning(f"CSVファイル先頭チェック中にエラー: {e}")
            return True  # エラー時はデフォルトでTrue

    def load_hf_dataset(self, repository: str) -> pl.DataFrame:
        """
        Hugging Face Dataset等からParquetを直接読み込む例。
        """
        self.logger.info(f"Hugging Face Datasetを読み込み: {repository}")
        try:
            return pl.read_parquet(repository)
        except Exception as e:
            self.logger.error(f"Parquet読み込み中にエラー: {e}")
            raise

    # ----------------------------------------------------------------------
    #  (2) DataFrameの前処理 (カラム補完・型変換等)
    # ----------------------------------------------------------------------
    def configure_import(
        self,
        source_df: pl.DataFrame,
        format_id: int = 0,
        language: Optional[str] = None
    ) -> tuple[pl.DataFrame, ImportConfig]:
        """
        インポート用の設定(ImportConfig)やカラム名の整合性を確認し、
        前処理済のDataFrameと Config を返す。

        Args:
            source_df (pl.DataFrame): 入力データ
            format_id (int): DB登録時のフォーマットID
            language (Optional[str]): 翻訳登録に使う言語コード

        Returns:
            (pl.DataFrame, ImportConfig)
        """
        self.logger.info(f"元データカラム: {list(source_df.columns)}")

        # カラム補完: (例) source_tag, tag が無ければ空文字列カラムを追加
        processed_df = self._ensure_minimum_columns(source_df)

        # カラム型の正規化など
        processed_df = self._normalize_typing(processed_df)

        # インポート設定オブジェクトを生成
        config = ImportConfig(
            format_id=format_id,
            language=language,
            column_names=processed_df.columns
        )
        return processed_df, config

    def _ensure_minimum_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        needed_cols = ["source_tag", "tag"]
        for col in needed_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit("").alias(col))
        return df

    def _normalize_typing(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        使用回数countなど数値カラムを正しい型に変換する。
        """
        if "count" in df.columns:
            df = df.with_columns(pl.col("count").cast(pl.Int64))
        return df

    # ----------------------------------------------------------------------
    #  (3) インポート処理 (DB登録)
    # ----------------------------------------------------------------------
    def import_data(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """
        外部ファイルから作った DataFrame を DBに登録する。
        - タグ正規化
        - タグ一括登録 & tag_id付与
        - usage_count 登録
        - 翻訳 (language, translation) 登録
        - deprecated_tags(エイリアス)登録
        """
        self.process_started.emit("インポート開始")
        self.logger.info("インポート開始")

        if self._cancel_flag:
            self.logger.info("キャンセルフラグが立っています。処理中断。")
            return

        try:
            # 1) タグを正規化 (source_tag / tagカラムの補完・クリーニング)
            normalized_df = self._register_svc.normalize_tags(df)

            # 2) タグ一括登録 → tag_id を付与
            enriched_df = self._register_svc.insert_tags_and_attach_id(normalized_df)

            # 3) usage_count の登録
            if "count" in enriched_df.columns:
                self._register_svc.update_usage_counts(enriched_df, config.format_id)

            # 4) 翻訳登録
            if config.language and "translation" in enriched_df.columns:
                self._register_svc.update_translations(enriched_df, config.language)

            # 5) deprecated_tags (エイリアス)
            if "deprecated_tags" in enriched_df.columns:
                self._register_svc.update_deprecated_tags(enriched_df, config.format_id)

            self.process_finished.emit("インポート完了")
            self.logger.info("インポート完了")

        except Exception as e:
            self.logger.error(f"インポート中にエラー: {e}")
            self.error_occurred.emit(str(e))
            raise

    # ----------------------------------------------------------------------
    #  (4) キャンセル / クリーンアップ
    # ----------------------------------------------------------------------
    def cancel(self):
        """
        インポート処理をユーザーがキャンセルしたい場合に呼び出すメソッド。
        """
        self.logger.info("インポート処理のキャンセル要求")
        self._cancel_flag = True

    def __del__(self):
        self.logger.debug("TagDataImporter インスタンス破棄")
