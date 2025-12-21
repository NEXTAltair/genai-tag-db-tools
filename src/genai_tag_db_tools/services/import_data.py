import logging
from collections.abc import Callable
from pathlib import Path

import polars as pl
from PySide6.QtCore import QObject, Signal
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.services.polars_schema import AVAILABLE_COLUMNS
from genai_tag_db_tools.services.tag_register import TagRegister


class ImportConfig:
    """インポート設定の簡易コンテナ。"""

    def __init__(
        self, format_id: int = 0, language: str | None = None, column_names: list[str] | None = None
    ):
        self.format_id = format_id
        self.language = language
        self.column_names = column_names or []


class TagDataImporter(QObject):
    """外部ファイルを読み込み、TagRegisterを使ってDBへ登録する。"""

    process_started = Signal(str)
    progress_updated = Signal(int, str)
    process_finished = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None, session_factory: Callable[[], Session] | None = None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

        repo = TagRepository(session_factory=session_factory) if session_factory else None
        self._register_svc = TagRegister(repository=repo)
        self._cancel_flag = False

    # ----------------------------------------------------------------------
    # (1) 読み込み
    # ----------------------------------------------------------------------
    def read_csv(self, csv_file_path: Path, has_header: bool = True) -> pl.DataFrame:
        """CSVを読み込み、DataFrameを返す。"""
        self.logger.info("CSVファイルを読み込み: %s", csv_file_path)
        try:
            return pl.read_csv(csv_file_path, has_header=has_header, encoding="utf-8")
        except Exception as e:
            self.logger.error("CSV読み込み中にエラー: %s", e)
            raise

    def decide_csv_header(self, csv_file_path: Path) -> bool:
        """先頭行を見てヘッダ有無を推定する。"""
        try:
            with open(csv_file_path, encoding="utf-8") as f:
                first_line = f.readline().strip()
                if any(col in first_line for col in AVAILABLE_COLUMNS):
                    return True
            return False
        except Exception as e:
            self.logger.warning("CSV先頭チェック中にエラー: %s", e)
            return True

    def load_hf_dataset(self, repository: str) -> pl.DataFrame:
        """Hugging Face Dataset等のParquetを読み込む。"""
        self.logger.info("Hugging Face Datasetを読み込み: %s", repository)
        try:
            return pl.read_parquet(repository)
        except Exception as e:
            self.logger.error("Parquet読み込み中にエラー: %s", e)
            raise

    # ----------------------------------------------------------------------
    # (2) 前処理
    # ----------------------------------------------------------------------
    def configure_import(
        self, source_df: pl.DataFrame, format_id: int = 0, language: str | None = None
    ) -> tuple[pl.DataFrame, ImportConfig]:
        """カラム補完/型調整後のDataFrameと設定を返す。"""
        self.logger.info("入力カラム: %s", list(source_df.columns))

        processed_df = self._ensure_minimum_columns(source_df)
        processed_df = self._normalize_typing(processed_df)

        config = ImportConfig(format_id=format_id, language=language, column_names=processed_df.columns)
        return processed_df, config

    def _ensure_minimum_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        for col in ["source_tag", "tag"]:
            if col not in df.columns:
                df = df.with_columns(pl.lit("").alias(col))
        return df

    def _normalize_typing(self, df: pl.DataFrame) -> pl.DataFrame:
        if "count" in df.columns:
            df = df.with_columns(pl.col("count").cast(pl.Int64))
        return df

    # ----------------------------------------------------------------------
    # (3) 登録処理
    # ----------------------------------------------------------------------
    def import_data(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """DataFrameをDBに登録する。"""
        self.process_started.emit("インポート開始")
        self.logger.info("インポート開始")

        if self._cancel_flag:
            self.logger.info("キャンセルフラグが立っているため中断します")
            return

        try:
            normalized_df = self._register_svc.normalize_tags(df)
            enriched_df = self._register_svc.insert_tags_and_attach_id(normalized_df)

            if "count" in enriched_df.columns:
                self._register_svc.update_usage_counts(enriched_df, config.format_id)

            if config.language and "translation" in enriched_df.columns:
                self._register_svc.update_translations(enriched_df, config.language)

            if "deprecated_tags" in enriched_df.columns:
                self._register_svc.update_deprecated_tags(enriched_df, config.format_id)

            self.process_finished.emit("インポート完了")
            self.logger.info("インポート完了")

        except Exception as e:
            self.logger.error("インポート中にエラー: %s", e)
            self.error_occurred.emit(str(e))
            raise

    # ----------------------------------------------------------------------
    # (4) キャンセル
    # ----------------------------------------------------------------------
    def cancel(self) -> None:
        """ユーザーキャンセルを受け付ける。"""
        self.logger.info("インポート処理のキャンセル要求")
        self._cancel_flag = True

    def __del__(self) -> None:
        self.logger.debug("TagDataImporter インスタンス破棄")
