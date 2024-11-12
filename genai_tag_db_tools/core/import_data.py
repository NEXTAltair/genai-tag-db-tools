from pathlib import Path
import logging
from typing import Optional
import sqlite3
from dataclasses import dataclass, field

import polars as pl
from PySide6.QtCore import QObject, Signal

from genai_tag_db_tools.core.processor import CSVToDatabaseProcessor
from genai_tag_db_tools.core.tag_search import TagSearcher
from genai_tag_db_tools.cleanup_str import TagCleaner

# パッケージのグローバル変数をインポート
from genai_tag_db_tools.config import db_path, AVAILABLE_COLUMNS


@dataclass
class ImportConfig:
    """インポート設定を保持するデータクラス"""

    format_id: int = 0  # 0 = Unknown
    language: Optional[str] = None
    column_names: list[str] = field(default_factory=list)


class TagDataImporter(QObject):
    """タグデータのインポートを行うクラス"""

    logger = logging.getLogger(__name__)

    # シグナルの定義
    importbutton_clicked = Signal()  # インポートボタンがクリックされた
    progress_updated = Signal(int, str)  # 進捗率, メッセージ
    process_started = Signal(str)  # プロセス名
    process_finished = Signal(str)  # プロセス名
    error_occurred = Signal(str)  # エラーメッセージ

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.conn = sqlite3.connect(db_path)
        self.tag_search = TagSearcher()
        self._cancel_flag = False

    @staticmethod
    def read_csv(csv_file_path: Path) -> pl.DataFrame:
        """CSVファイルを読み込む

        Args:
            csv_file_path (Path): 読み込むファイルのパス

        Returns:
            pl.DataFrame: 読み込んだデータフレーム
        """
        # 一行目だけを読み込んで `AVAILABLE_COLUMNS` に含まれるカラム名があるか確認
        with open(csv_file_path, "r") as f:
            first_line = f.readline().strip()
            if any(col in first_line for col in AVAILABLE_COLUMNS):
                TagDataImporter.logger.info(
                    f"ヘッダありとしてCSVファイルを読み込み: {csv_file_path}"
                )
                return pl.read_csv(csv_file_path)
            else:
                TagDataImporter.logger.info(
                    f"ヘッダなしとしてCSVファイルを読み込み: {csv_file_path}"
                )
                return pl.read_csv(csv_file_path, has_header=False)

    @staticmethod
    def load_hf_dataser(repository: str) -> pl.DataFrame:
        """Hugging Face Datasetのデータを読み込む

        Args:
            repository (str): URL

        Returns:
            pl.DataFrame: 読み込んだデータフレーム
        """
        TagDataImporter.logger.info(f"Hugging Face Datasetを読み込み: {repository}")
        return pl.read_parquet(repository)

    def configure_import(
        self, source_df: pl.DataFrame
    ) -> tuple[pl.DataFrame, ImportConfig]:
        """
        インポート設定を行う

        この後の処理を行うためのヘッダーを正則化したデータフレームを作成する

        Args:
            source_df (pl.DataFrame): カラム名を確認するデータフレームの元データ

        Returns:
            add_db_df (pl.DataFrame): インポートするための加工を行ったデータフレーム
            ImportConfig: インポート設定オブジェクト
        """
        TagDataImporter.logger.info(f"現在のカラム名: {list(source_df.columns)}")
        TagDataImporter.logger.info(
            f"データベースに登録できるカラム名: {AVAILABLE_COLUMNS}"
        )

        language = self.get_language()

        # 言語に基づいて翻訳データのカラムをレコード形式に変換
        if language and language in source_df.columns:
            source_df = source_df.melt(
                id_vars=["source_tag"],
                value_vars=[language],
                variable_name="language",
                value_name="translation",
            )
            TagDataImporter.logger.info(
                f"カラム '{language}' をレコード形式に変換しました。"
            )

        existing_columns = [
            col for col in AVAILABLE_COLUMNS if col in source_df.columns
        ]
        missing_columns = [
            col for col in AVAILABLE_COLUMNS if col not in existing_columns
        ]

        TagDataImporter.logger.debug(f"既存のカラム: {existing_columns}")
        TagDataImporter.logger.info(f"不足しているカラム: {missing_columns}")

        # 既存のカラムのみを持つ新しいデータフレームを作成
        add_db_df = source_df.select(existing_columns).clone()

        # ここで add_db_columns を初期化
        add_db_columns = existing_columns.copy()

        # 不足しているカラムをリネームまたは追加
        for col in missing_columns:
            user_input = self.get_user_input_for_column(col, source_df)
            if user_input:
                if user_input in source_df.columns:
                    add_db_df = add_db_df.with_columns(source_df[user_input].alias(col))
                    TagDataImporter.logger.info(
                        f"カラム '{col}' を '{user_input}' から追加しました。"
                    )
                else:
                    TagDataImporter.logger.warning(
                        f"ソースデータフレームに '{user_input}' カラムが存在しません。"
                    )
                    continue
                add_db_columns.append(col)  # 新しく追加されたカラムを一覧に追加
            else:
                TagDataImporter.logger.info(
                    f"カラム '{col}' のマッピングをスキップしました。"
                )

        format_id = self.get_format_id()

        return add_db_df, ImportConfig(
            format_id=format_id,
            language=language,
            column_names=add_db_columns,
        )

    def get_user_input_for_column(self, column: str, source_df: pl.DataFrame) -> str:
        """
        ユーザーからの入力を取得してカラムをリネームする

        Args:
            column (str): リネーム対象のカラム名
            source_df (pl.DataFrame): 加工前のデータフレーム

        Returns:
            str: リネーム後のカラム名または空文字
        """
        while True:
            user_input = input(
                f"カラム '{column}' の対応するソースカラム名を入力してください（存在しない場合はスキップ）:"
            ).strip()
            if not user_input:
                return ""
            if user_input in source_df.columns:
                return user_input
            TagDataImporter.logger.warning(
                f"ソースカラム '{user_input}' は存在しません。再度入力してください。"
            )

    def get_format_id(self) -> int:
        format_name = input("フォーマット名を選択（省略可能）: ").strip()
        if not format_name:
            return 0
        try:
            return self.tag_search.get_format_id(format_name)
        except ValueError as e:
            TagDataImporter.logger.error(str(e))
            return 0

    def get_language(self) -> Optional[str]:
        lang = input("言語を入力してください（省略可能）: ").strip()
        return lang if lang else None

    def _normalize_tags(self, df: pl.DataFrame) -> pl.DataFrame:
        """データフレームに source_tag から tag へ変換したデータを追加

        Args:
            df (pl.DataFrame): 処理するデータフレーム

        Returns:
            pl.DataFrame: 正規化されたデータフレーム
        """
        if "source_tag" not in df.columns:
            error_msg = "「source_tag」列がデータフレームにありません"
            TagDataImporter.logger.error(error_msg)
            raise KeyError(error_msg)

        if df["source_tag"].is_null().all():
            error_msg = "「source_tag」列にデータがありません"
            TagDataImporter.logger.error(error_msg)
            raise ValueError(error_msg)

        if "tag" not in df.columns:
            cleaned_tags = [TagCleaner.clean_format(tag) for tag in df["source_tag"]]
            df = df.with_columns(pl.Series("tag", cleaned_tags))
        return df

    def _insert_tags_to_db(self, df: pl.DataFrame) -> None:
        """TAGSテーブルにデータを登録

        Args:
            df (pl.DataFrame): 処理するデータフレーム
        """
        tag_df = df.select(["source_tag", "tag"])
        tag_df.write_database("TAGS", self.conn)

    def _add_tag_id_column(self, df: pl.DataFrame) -> pl.DataFrame:
        """データベースから  tag_id を取得 df にカラムとして追加

        Args:
            df (pl.DataFrame): 処理するデータフレーム
        """
        tag_ids = [self.tag_search.find_tag_id(tag) for tag in df["tag"]]
        return df.with_columns(pl.Series("tag_id", tag_ids))

    def _process_translations(self, df: pl.DataFrame, language: str) -> None:
        """TAG_TRANSLATIONSテーブルの処理

        Args:
            df (pl.DataFrame): 処理するデータフレーム
            tag_ids (dict[str, int]): source_tagからtag_idへのマッピング
            language (str): 言語コード
        """
        translations = []
        for row in df.iter_rows(named=True):
            if row["translation"]:
                tag_id = tag_ids[row["source_tag"]]
                for trans in row["translation"].split(","):
                    trans = trans.strip()
                    if trans:
                        translations.append((tag_id, language, trans))

        if translations:
            self.cursor.executemany(
                """
                INSERT OR IGNORE INTO TAG_TRANSLATIONS (tag_id, language, translation)
                VALUES (?, ?, ?)
            """,
                translations,
            )

    def _process_tag_status(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """TAG_STATUSテーブルの処理

        Args:
            df (pl.DataFrame): 処理するデータフレーム
            tag_ids (dict[str, int]): source_tagからtag_idへのマッピング
            config (ImportConfig): インポート設定
        """
        status_records = []
        for row in df.iter_rows(named=True):
            tag_id = tag_ids[row["source_tag"]]
            type_id = config.type_mappings.get(row.get("type", "general"), 0)

            # エイリアス情報の処理
            is_alias = False
            preferred_tag_id = None
            if "deprecated_tag" in df.columns and row["deprecated_tag"]:
                is_alias = True
                if row["deprecated_tag"] in tag_ids:
                    preferred_tag_id = tag_ids[row["deprecated_tag"]]

            status_records.append(
                (
                    tag_id,
                    config.format_id,
                    type_id,
                    int(is_alias),
                    preferred_tag_id or tag_id,
                )
            )

        if status_records:
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO TAG_STATUS
                (tag_id, format_id, type_id, alias, preferred_tag_id)
                VALUES (?, ?, ?, ?, ?)
            """,
                status_records,
            )

    def _process_usage_counts(
        self, df: pl.DataFrame, tag_ids: dict[str, int], format_id: int
    ) -> None:
        """TAG_USAGE_COUNTSテーブルの処理

        Args:
            df (pl.DataFrame): 処理するデータフレーム
            tag_ids (dict[str, int]): source_tagからtag_idへのマッピング
            format_id (int): フォーマットID
        """
        usage_counts = []
        for row in df.iter_rows(named=True):
            if "count" in row and row["count"]:
                tag_id = tag_ids[row["source_tag"]]
                count = int(row["count"])
                usage_counts.append((tag_id, format_id, count))

        if usage_counts:
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO TAG_USAGE_COUNTS (tag_id, format_id, count)
                VALUES (?, ?, ?)
            """,
                usage_counts,
            )

    def import_data(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """データをインポートするメソッド"""
        try:
            self.process_started.emit("インポート開始")
            normalized_df = self._normalize_tags(df)
            self._insert_tags_to_db(normalized_df)
            tag_ids = self.tag_search.get_tag_ids(normalized_df["tag"].to_list())
            normalized_df = self._add_tag_id_column(normalized_df)
            self._process_translations(normalized_df, config.language)
            self._process_tag_status(normalized_df, config)
            self._process_usage_counts(normalized_df, tag_ids, config.format_id)
            self.conn.commit()
            self.process_finished.emit("インポート完了")
        except Exception as e:
            self.error_occurred.emit(str(e))
            self.conn.rollback()

    def cancel(self) -> None:
        """処理のキャンセル"""
        self._cancel_flag = True
        TagDataImporter.logger.info("処理がキャンセルされました")

    def __del__(self):
        """デストラクタ - リソースのクリーンアップ"""
        try:
            if hasattr(self, "conn") and self.conn:
                self.conn.commit()
                self.conn.close()
        except Exception as e:
            TagDataImporter.logger.error(f"クリーンアップ中にエラーが発生: {str(e)}")


if __name__ == "__main__":
    # danbooruデータのインポート設定
    danbooru_config = ImportConfig(
        format_id=1,  # danbooru
        column_names=["source_tag", "translation"],  # Add the required column names
        language="ja-JP",
    )

    # データの読み込み（例：danbooru_klein10k_jp.csv）
    df = pl.read_csv("danbooru_klein10k_jp.csv")

    # インポーターの初期化と実行
    importer = TagDataImporter()
    importer.import_data(df, danbooru_config)
