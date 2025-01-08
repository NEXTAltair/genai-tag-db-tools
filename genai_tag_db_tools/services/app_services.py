# genai_tag_db_tools/services/app_service.py

import logging
import polars as pl
from typing import Optional

from PySide6.QtCore import QObject, Signal

from genai_tag_db_tools.services.import_data import TagDataImporter, ImportConfig
from genai_tag_db_tools.services.tag_search import TagSearcher


class GuiServiceBase(QObject):
    """
    PySide6 のシグナルや共通のロガー初期化などを行う基底クラス。
    進捗通知やエラー通知など、GUIとの連携でよく使う機能をまとめる。
    """

    # GUI向けに進捗や完了、エラーを通知するためのシグナルを共通定義
    progress_updated = Signal(int, str)   # (進捗度, メッセージ)
    process_finished = Signal(str)        # (完了時のメッセージや処理名)
    error_occurred = Signal(str)          # (エラー内容)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        # 各サービスクラスで共通して使いたいロガー
        self.logger = logging.getLogger(self.__class__.__name__)


class TagCoreService:
    """
    タグ検索やフォーマット取得など、DB操作のコアロジックをまとめたクラス。
    すべてのサービス(Import/Clean/Cleanup/Search/etc.)が共通で使える機能を集約。
    """

    def __init__(self, searcher: Optional[TagSearcher] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        # TagSearcher を内包
        self._searcher = searcher or TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """
        DBからタグフォーマット一覧を取得して返す。
        """
        return self._searcher.get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        """
        DBから言語一覧を取得して返す。
        """
        return self._searcher.get_tag_languages()

    def get_format_id(self, format_name: str) -> Optional[int]:
        """
        フォーマット名からフォーマットIDを取得。
        """
        return self._searcher.tag_repo.get_format_id(format_name)

    def convert_tag(self, tag: str, format_id: int) -> str:
        """
        単一のタグ文字列を指定フォーマットIDに基づき変換。
        TagSearcher.convert_tag() を内部利用。
        """
        return self._searcher.convert_tag(tag, format_id)


class TagCleanerService(GuiServiceBase):
    """
    GUIなどで「タグの一括変換」や「フォーマット一覧取得 + 'All'を先頭に追加」など
    軽量な変換ロジックを行うサービスクラス。

    - DBアクセスやタグ操作は TagCoreService に委譲し、
    - GUI用のシグナルやロガーは GuiServiceBase の継承で使う。
    """

    def __init__(self, parent: Optional[QObject] = None, core: Optional[TagCoreService] = None):
        super().__init__(parent)
        self._core = core or TagCoreService()

    def get_tag_formats(self) -> list[str]:
        """
        コアロジックのフォーマット一覧を取得し、先頭に 'All' を追加して返す。
        """
        format_list = ["All"]
        format_list.extend(self._core.get_tag_formats())
        return format_list

    def convert_prompt(self, prompt: str, format_name: str) -> str:
        """
        カンマ区切りの複数タグを DBで検索・変換し、一括で置き換える。
        例: "1boy, 1girl" + "e621" → DBを参照して各タグを変換 → "male, female" (仮)
        """
        self.logger.info("TagCleanerService: convert_prompt() called")

        # フォーマットIDを取得
        format_id = self._core.get_format_id(format_name)
        if format_id is None:
            self.logger.warning(f"Unknown format: {format_name}")
            return prompt

        raw_tags = [t.strip() for t in prompt.split(",")]
        converted_list = []
        for tag in raw_tags:
            converted = self._core.convert_tag(tag, format_id)
            converted_list.append(converted)

        # カンマ区切りで結合して返す
        return ", ".join(converted_list)


class TagImportService(GuiServiceBase):
    """
    データインポートを担当するサービスクラス。
    - DBとのやり取りは TagDataImporter (内部), TagCoreService(フォーマット周り) を使う
    - PySide6 Signals (progress_updated, process_finished, error_occurred) を持つ
    """

    def __init__(
        self,
        parent: Optional[QObject] = None,
        importer: Optional[TagDataImporter] = None,
        core: Optional[TagCoreService] = None,
    ):
        super().__init__(parent)
        self._importer = importer or TagDataImporter()
        self._core = core or TagCoreService()

        # TagDataImporter が発行するシグナルを、このクラスのシグナルにリレーする例
        self._importer.progress_updated.connect(self._on_importer_progress)
        self._importer.process_finished.connect(self._on_importer_finished)
        self._importer.error_occurred.connect(self._on_importer_error)

    def _on_importer_progress(self, value: int, message: str):
        """
        TagDataImporter から受け取った進捗を、このサービスの progress_updated で再通知。
        """
        self.logger.debug(f"Import progress: {value}% {message}")
        self.progress_updated.emit(value, message)

    def _on_importer_finished(self, msg: str):
        """
        Import完了を再通知。
        """
        self.logger.info("Import finished.")
        self.process_finished.emit(msg)

    def _on_importer_error(self, err_msg: str):
        """
        エラー発生を再通知。
        """
        self.logger.error(f"Import error: {err_msg}")
        self.error_occurred.emit(err_msg)

    @property
    def importer(self) -> TagDataImporter:
        """
        GUI側が TagDataImporter のシグナルやメソッドに直接アクセスしたい場合に使う。
        ここではPropertyとして公開。
        """
        return self._importer

    # ----------------------------------------------------------------------
    #  インポート関連メソッド
    # ----------------------------------------------------------------------

    def import_data(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """
        TagDataImporter を用いてデータフレームをDBにインポートする。
        """
        self.logger.info("TagImportService: import_data() called.")
        self._importer.import_data(df, config)

    def cancel_import(self) -> None:
        """
        インポート処理をキャンセル。
        """
        self.logger.info("TagImportService: cancel_import() called.")
        self._importer.cancel()

    # ----------------------------------------------------------------------
    #  DB情報取得関連 (TagCoreService 経由)
    # ----------------------------------------------------------------------

    def get_tag_formats(self) -> list[str]:
        """
        フォーマット一覧を取得し、GUIで 'All' 不要なら除去する例。
        """
        return [f for f in self._core.get_tag_formats() if f != "All"]

    def get_tag_languages(self) -> list[str]:
        """
        DBから言語一覧を取得し、'All' を外す例。
        """
        return [lang for lang in self._core.get_tag_languages() if lang != "All"]

    def get_format_id(self, format_name: str) -> Optional[int]:
        return self._core.get_format_id(format_name)


if __name__ == "__main__":
    """
    簡易動作テスト:
      - TagCleanerService で複数タグを変換
      - TagImportService でデータインポート(ダミー)
    """
    import sys

    # 1) タグクリーナーのテスト
    cleaner = TagCleanerService()
    all_formats = cleaner.get_tag_formats()
    print("DBから取得したフォーマット一覧 (+ All):", all_formats)

    sample_text = "1boy, 1girl, 2boys"
    format_name = "e621"  # 例: DBに登録してあるフォーマット名
    result = cleaner.convert_prompt(sample_text, format_name)
    print(f"[convert_prompt] '{sample_text}' → '{result}' (format='{format_name}')")

    # 2) インポートサービスのテスト
    importer_service = TagImportService()
    # ダミーDataFrame
    df = pl.DataFrame({"tag": ["1boy", "2girls"], "count": [10, 20]})
    config = ImportConfig(format_id=importer_service.get_format_id("danbooru"), language="en")
    importer
