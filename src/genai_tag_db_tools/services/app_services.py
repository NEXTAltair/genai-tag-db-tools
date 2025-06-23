# genai_tag_db_tools/services/app_services.py

import logging
from typing import Any

import polars as pl
from PySide6.QtCore import QObject, Signal
from sqlalchemy.orm import Session

from genai_tag_db_tools.data.tag_repository import TagRepository
from genai_tag_db_tools.services.import_data import ImportConfig, TagDataImporter
from genai_tag_db_tools.services.tag_search import TagSearcher
from genai_tag_db_tools.services.tag_statistics import TagStatistics


class GuiServiceBase(QObject):
    """
    PySide6 のシグナルや共通のロガー初期化などを行う基底クラス。
    進捗通知やエラー通知など、GUIとの連携でよく使う機能をまとめる。
    """

    # GUI向けに進捗や完了、エラーを通知するためのシグナルを共通定義
    progress_updated = Signal(int, str)  # (進捗度, メッセージ)
    process_finished = Signal(str)  # (完了時のメッセージや処理名)
    error_occurred = Signal(str)  # (エラー内容)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        # 各サービスクラスで共通して使いたいロガー
        self.logger = logging.getLogger(self.__class__.__name__)


class TagCoreService:
    """
    タグ検索やフォーマット取得など、DB操作のコアロジックをまとめたクラス。
    すべてのサービス(Import/Clean/Cleanup/Search/etc.)が共通で使える機能を集約。
    """

    def __init__(self, searcher: TagSearcher | None = None):
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

    def get_format_id(self, format_name: str) -> int:
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


class TagSearchService(GuiServiceBase):
    """
    TagSearcherを内部で利用し、GUI用のメソッド（検索やフォーマット一覧取得など）をまとめる。
    """

    def __init__(self, parent: QObject | None = None, searcher: TagSearcher | None = None):
        super().__init__(parent)
        self._searcher = searcher or TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """
        DB からタグフォーマット一覧を取得。
        """
        try:
            return self._searcher.get_tag_formats()
        except Exception as e:
            self.logger.error(f"フォーマット一覧取得中にエラー: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_tag_languages(self) -> list[str]:
        """
        DB から言語一覧を取得。
        """
        try:
            return self._searcher.get_tag_languages()
        except Exception as e:
            self.logger.error(f"言語一覧取得中にエラー: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_tag_types(self, format_name: str | None) -> list[str]:
        """
        指定フォーマットに紐づくタグタイプ一覧を取得。

        Args:
            format_name (str): フォーマット名。None の場合は全検索。
        """
        try:
            if format_name is None:
                return self._searcher.get_all_types()
            return self._searcher.get_tag_types(format_name)
        except Exception as e:
            self.logger.error(f"タグタイプ一覧取得中にエラー: {e}")
            self.error_occurred.emit(str(e))
            raise

    def search_tags(
        self,
        keyword: str,
        partial: bool = False,
        format_name: str | None = None,
        type_name: str | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
    ) -> pl.DataFrame:
        """
        タグを検索し、結果を list[dict] 形式で返す想定。
        partial=True の場合は部分一致、partial=False は完全一致。
        format_name=None の場合はフォーマット指定なし(全検索)
        """
        try:
            return self._searcher.search_tags(
                keyword=keyword,
                partial=partial,
                format_name=format_name,
                type_name=type_name,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=alias,
            )
        except Exception as e:
            self.logger.error(f"タグ検索中にエラー: {e}")
            self.error_occurred.emit(str(e))
            raise


class TagCleanerService(GuiServiceBase):
    """
    GUIなどで「タグの一括変換」や「フォーマット一覧取得 + 'All'を先頭に追加」など
    軽量な変換ロジックを行うサービスクラス。

    - DBアクセスやタグ操作は TagCoreService に委譲し、
    - GUI用のシグナルやロガーは GuiServiceBase の継承で使う。
    """

    def __init__(self, parent: QObject | None = None, core: TagCoreService | None = None):
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
        parent: QObject | None = None,
        importer: TagDataImporter | None = None,
        core: TagCoreService | None = None,
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
        DB に登録されているフォーマット一覧を取得。
        """
        return self._core.get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        """
        DB に登録されている言語一覧を取得。
        """
        return self._core.get_tag_languages()

    def get_format_id(self, format_name: str) -> int:
        return self._core.get_format_id(format_name)


class TagRegisterService(GuiServiceBase):
    """
    GUIに進捗やエラーを通知するために、GuiServiceBaseを継承したタグ登録サービス。
    """

    def __init__(self, parent=None, repository: TagRepository | None = None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else TagRepository()

    def register_or_update_tag(self, tag_info: dict) -> int:
        """
        タグ登録/更新処理を行い、何らかのDBエラーが起きたらシグナルでGUIに通知する。
        """
        try:
            normalized_tag = tag_info.get("normalized_tag")
            source_tag = tag_info.get("source_tag")
            format_name = tag_info.get("format_name", "")
            type_name = tag_info.get("type_name", "")
            usage_count = tag_info.get("use_count", 0)
            language = tag_info.get("language", "")
            translation = tag_info.get("translation", "")

            if not normalized_tag or not source_tag:
                raise ValueError("タグまたは元タグが空です。")

            # 1) フォーマットID, タイプID の取得
            fmt_id = self._repo.get_format_id(format_name)
            type_id = None
            if type_name:
                type_id = self._repo.get_type_id(type_name)

            # 2) タグを作成 or 既存ID取得
            tag_id = self._repo.create_tag(source_tag, normalized_tag)

            # 3) usage_count (使用回数) 登録
            if usage_count > 0:
                self._repo.update_usage_count(tag_id, fmt_id, usage_count)

            # 4) 翻訳登録
            if language and translation:
                self._repo.add_or_update_translation(tag_id, language, translation)

            # 5) TagStatus 更新 (alias=Falseで登録例)
            self._repo.update_tag_status(
                tag_id=tag_id, format_id=fmt_id, alias=False, preferred_tag_id=tag_id, type_id=type_id
            )

            return tag_id

        except Exception as e:
            self.logger.error(f"タグ登録中にエラー発生: {e}")
            # <-- GUIにエラーを通知するシグナルを発行
            self.error_occurred.emit(str(e))
            # エラーを再度外に投げたい場合はここで raise してもよい
            raise

    def get_tag_details(self, tag_id: int) -> pl.DataFrame:
        """
        登録後のタグ詳細を取得してDataFrame化して返す。
        (DBエラーが起きる可能性がある場合も同様にシグナルで通知)
        """
        try:
            tag_obj = self._repo.get_tag_by_id(tag_id)
            if not tag_obj:
                return pl.DataFrame()

            status_list = self._repo.list_tag_statuses(tag_id)
            translations = self._repo.get_translations(tag_id)

            rows = [
                {
                    "tag": tag_obj.tag,
                    "source_tag": tag_obj.source_tag,
                    "formats": [s.format_id for s in status_list],
                    "types": [s.type_id for s in status_list],
                    "total_usage_count": sum(
                        self._repo.get_usage_count(tag_id, s.format_id) or 0 for s in status_list
                    ),
                    "translations": {t.language: t.translation for t in translations},
                }
            ]

            return pl.DataFrame(rows)

        except Exception as e:
            self.logger.error(f"タグ詳細取得中にエラー発生: {e}")
            self.error_occurred.emit(str(e))
            raise


class TagStatisticsService(GuiServiceBase):
    """
    TagStatistics(ロジッククラス)を内部に持ち、
    GUI から呼ばれる「統計取得」「計算」等の処理をまとめたサービスクラス。

    - TagStatistics はデータベースにアクセスし Polars DataFrame や dict で統計を返す
    - GUI層ではシグナルによるエラーハンドリングを利用可能
    """

    def __init__(
        self,
        parent: QObject | None = None,
        session: Session | None = None,
    ):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._stats = TagStatistics(session=session)  # ← Polarsベースの統計処理

    def get_general_stats(self) -> dict[str, Any]:
        """
        全体的なサマリ(総タグ数/エイリアス数など)を dict で取得
        """
        try:
            return self._stats.get_general_stats()
        except Exception as e:
            self.logger.error(f"統計取得中にエラーが発生: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_usage_stats(self) -> pl.DataFrame:
        """
        タグ使用回数の DataFrame を取得 (Polars)
        columns: [tag_id, format_name, usage_count]
        """
        try:
            return self._stats.get_usage_stats()
        except Exception as e:
            self.logger.error(f"使用回数統計取得中にエラーが発生: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_type_distribution(self) -> pl.DataFrame:
        """
        タイプ(タグカテゴリ)別のタグ数分布
        columns: [format_name, type_name, tag_count]
        """
        try:
            return self._stats.get_type_distribution()
        except Exception as e:
            self.logger.error(f"タイプ分布統計取得中にエラーが発生: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_translation_stats(self) -> pl.DataFrame:
        """
        翻訳情報の統計
        columns: [tag_id, total_translations, languages (List[str])]
        """
        try:
            return self._stats.get_translation_stats()
        except Exception as e:
            self.logger.error(f"翻訳統計取得中にエラーが発生: {e}")
            self.error_occurred.emit(str(e))
            raise


if __name__ == "__main__":
    """
    簡易動作テスト:
      - TagCleanerService で複数タグを変換
      - TagImportService でデータインポート(ダミー)
    """

    # 1) タグクリーナーのテスト (Polarsではなく単純な文字列変換)
    cleaner = TagCleanerService()
    all_formats = cleaner.get_tag_formats()
    print("DBから取得したフォーマット一覧 (+ All):", all_formats)

    sample_text = "1boy, 1girl, 2boys"
    format_name = "e621"  # 例: DBに登録してあるフォーマット名
    result = cleaner.convert_prompt(sample_text, format_name)
    print(f"[convert_prompt] '{sample_text}' → '{result}' (format='{format_name}')")

    # 2) インポートサービスのテスト (Polars DataFrame を用意)
    importer_service = TagImportService()
    dummy_df = pl.DataFrame({"tag": ["1boy", "2girls"], "count": [10, 20]})
    config = ImportConfig(format_id=importer_service.get_format_id("danbooru"), language="en")

    importer_service.import_data(dummy_df, config)
    print("Import finished.")
