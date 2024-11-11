from pathlib import Path
import logging
import re
import select
import sqlite3
from typing import Optional
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

    format_id: int
    language: Optional[str] = None
    # 最低限 source_tag と format_id のカラムは必要
    column_names: list[str] = field(default_factory=list)


class TagDataImporter(QObject):
    """タグデータのインポートを行うクラス"""

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
        self.logger = logging.getLogger(__name__)
        self._cancel_flag = False

    def read_csv(self, file_path: Path) -> pl.DataFrame:
        """CSVファイルを読み込む

        Args:
            file_path (Path): 読み込むファイルのパス

        Returns:
            pl.DataFrame: 読み込んだデータフレーム
        """
        # 一行目だけを読み込んで `AVAILABLE_COLUMNS` に含まれるカラム名があるか確認
        with open(file_path, "r") as f:
            first_line = f.readline().strip()
            if not any(col in first_line for col in AVAILABLE_COLUMNS):
                self.logger.info(f"ヘッダありとしてCSVファイルを読み込み: {file_path}")
                return pl.read_csv(file_path)
            else:
                self.logger.info(f"ヘッダなしとしてCSVファイルを読み込み: {file_path}")
                return pl.read_csv(file_path, has_header=False)

    def load_hf_dataser(self, repository: str) -> pl.DataFrame:
        """Hugging Face Datasetのデータを読み込む

        Args:
            repository (str): URL

        Returns:
            pl.DataFrame: 読み込んだデータフレーム
        """
        self.logger.info(f"Hugging Face Datasetを読み込み: {repository}")
        return pl.read_parquet(repository)

    def configure_import(self, source_df: pl.DataFrame) -> ImportConfig:
        """インポート設定を行う
        一つのデータに複数のサイトから得たタグ情報があることは想定しない
        どのフォーマットを選択するかはユーザーによる手動選択とする
        prompt-all-in-one の csv の形式はカラムに名前がついていない
        その類のデータに対応するため手動でカラム名を選択する

        Args:
            df (pl.DataFrame): カラム名を確認するデータフレーム

        Returns:
            ImportConfig: 設定されたインポート設定
        """
        print("現在のカラム名:", list(source_df.columns))
        print("選択可能なカラム名:", AVAILABLE_COLUMNS)

        auto_selected = self.auto_select_columns(source_df)
        manual_mappings = self.map_missing_columns(source_df, auto_selected)
        updated_df = self.apply_mappings(source_df, manual_mappings)
        selected_columns = auto_selected + list(manual_mappings.keys())

        format_id = self.get_format_id()
        language = self.get_language()

        return ImportConfig(
            format_id=format_id,
            language=language,
            column_names=selected_columns,
        )

    def auto_select_columns(self, source_df: pl.DataFrame) -> list[str]:
        return [col for col in AVAILABLE_COLUMNS if col in source_df.columns]

    def map_missing_columns(
        self, source_df: pl.DataFrame, auto_selected: list[str]
    ) -> dict[str, str]:
        missing = [col for col in AVAILABLE_COLUMNS if col not in auto_selected]
        mappings = {}
        for col in missing:
            while True:
                user_input = input(
                    f"カラム '{col}' の対応するソースカラム名を入力してください（存在しない場合はスキップ）: "
                ).strip()
                if user_input == "":
                    print(f"カラム '{col}' のマッピングをスキップします。")
                    break
                elif user_input in source_df.columns:
                    mappings[col] = user_input
                    print(
                        f"カラム '{col}' はソースカラム '{user_input}' にマッピングされました。"
                    )
                    break
                else:
                    print(
                        f"ソースカラム '{user_input}' は存在しません。再度入力してください。"
                    )
        return mappings

    def apply_mappings(
        self, source_df: pl.DataFrame, mappings: dict[str, str]
    ) -> pl.DataFrame:
        for target, source in mappings.items():
            source_df = source_df.with_columns(pl.col(source).alias(target))
        return source_df

    def get_format_id(self) -> int:
        format_name = input("フォーマット名を選択: ")
        return self.tag_search.get_format_id(format_name)

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
            self.logger.error(error_msg)
            raise KeyError(error_msg)

        if df["source_tag"].is_null().all():
            error_msg = "「source_tag」列にデータがありません"
            self.logger.error(error_msg)
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
        self.logger.info("処理がキャンセルされました")

    def __del__(self):
        """デストラクタ - リソースのクリーンアップ"""
        try:
            if hasattr(self, "conn") and self.conn:
                self.conn.commit()
                self.conn.close()
        except Exception as e:
            self.logger.error(f"クリーンアップ中にエラーが発生: {str(e)}")


if __name__ == "__main__":
    # danbooruデータのインポート設定
    danbooru_config = ImportConfig(
        format_id=1,  # danbooru
        column_names=["source_tag", "translation"],  # Add the required column names
        language="ja-JP",
    )

    # データの読み込み（例：danbooru_klein10k_jp.csv）
    df = pl.read_csv("danbooru_klein10k_jp.csv")

    # 必要なカラムのリネームと型変換
    df = df.rename(
        {
            "source_tag": "source_tag",
            "japanese": "translation",
            # 他の必要なカラムのリネーム
        }
    )

    # インポーターの初期化と実行
    importer = TagDataImporter(Path("tags_v3.db"))
    importer.import_data(df, danbooru_config)
