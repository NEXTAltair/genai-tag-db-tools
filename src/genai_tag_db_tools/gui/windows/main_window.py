import logging
import sys

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from genai_tag_db_tools.gui.designer.MainWindow_ui import Ui_MainWindow
from genai_tag_db_tools.gui.widgets.tag_cleaner import TagCleanerWidget
from genai_tag_db_tools.gui.widgets.tag_import import TagDataImportDialog
from genai_tag_db_tools.gui.widgets.tag_register import TagRegisterWidget
from genai_tag_db_tools.gui.widgets.tag_search import TagSearchWidget
from genai_tag_db_tools.gui.widgets.tag_statistics import TagStatisticsWidget


class MainWindow(QMainWindow, Ui_MainWindow):
    """メインウィンドウクラス"""

    def __init__(self):
        """初期化"""
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        try:
            # サービスの初期化
            self._initialize_services()

            # UIのセットアップ（この時点でウィジェットが作成される）
            self.setupUi(self)

            # ウィジェットの初期化とシグナル接続
            self._initialize_widgets()
            self._connect_signals()

            self.setWindowTitle("タグデータベースツール")
            self.logger.info("MainWindow initialization completed successfully")

        except Exception as e:
            self.logger.error(f"Error during MainWindow initialization: {e}", exc_info=True)
            QMessageBox.critical(
                self, "初期化エラー", f"アプリケーションの初期化中にエラーが発生しました: {e}"
            )
            raise

    def _initialize_services(self):
        """サービスの初期化"""
        try:
            from genai_tag_db_tools.services.app_services import (
                TagCleanerService,
                TagImportService,
                TagRegisterService,
                TagSearchService,
                TagStatisticsService,
            )

            self.tag_search_service = TagSearchService()
            self.tag_cleaner_service = TagCleanerService()
            self.tag_register_service = TagRegisterService()
            self.tag_import_service = TagImportService()
            self.tag_statistics_service = TagStatisticsService()
            self.logger.info("Services initialized successfully")

        except Exception as e:
            self.logger.error(f"Error initializing services: {e}", exc_info=True)
            raise

    def _initialize_widgets(self):
        """ウィジェットの初期化とシグナル接続"""
        try:
            # TagSearchWidget
            if isinstance(self.tagSearch, TagSearchWidget):
                self.logger.debug("Initializing TagSearchWidget")
                self.tagSearch._service = self.tag_search_service
                self.tagSearch.error_occurred.connect(self.on_service_error)
                self.tagSearch.initialize_ui()

            # TagCleanerWidget
            if isinstance(self.tagCleaner, TagCleanerWidget):
                self.logger.debug("Initializing TagCleanerWidget")
                self.tagCleaner.initialize(self.tag_cleaner_service)

            # TagRegisterWidget
            if isinstance(self.tagRegister, TagRegisterWidget):
                self.logger.debug("Initializing TagRegisterWidget")
                self.tagRegister.search_service = self.tag_search_service
                self.tagRegister.register_service = self.tag_register_service
                self.tagRegister.initialize()

            # TagStatisticsWidget
            if isinstance(self.tagStatistics, TagStatisticsWidget):
                self.logger.debug("Initializing TagStatisticsWidget")
                self.tagStatistics.service = self.tag_statistics_service
                # 時間かかるので統計情報は初期化しない
                # self.tagStatistics.initialize()

            self.logger.info("All widgets initialized successfully")

        except Exception as e:
            self.logger.error(f"Error initializing widgets: {e}", exc_info=True)
            raise

    def _connect_signals(self):
        """シグナルの接続"""
        try:
            # メニューアクション
            self.actionimport.triggered.connect(self.on_actionimport_triggered)

            # 各サービスのエラーシグナルをステータスバーに接続
            self.tag_search_service.error_occurred.connect(self.on_service_error)
            self.tag_cleaner_service.error_occurred.connect(self.on_service_error)
            self.tag_register_service.error_occurred.connect(self.on_service_error)
            self.tag_import_service.error_occurred.connect(self.on_service_error)
            self.tag_statistics_service.error_occurred.connect(self.on_service_error)

            self.logger.info("Signals connected successfully")

        except Exception as e:
            self.logger.error(f"Error connecting signals: {e}", exc_info=True)
            raise

    @Slot()
    def on_actionimport_triggered(self):
        """
        メニューやツールバー上の 'Import' アクションが押された時の処理
        """
        # ファイル選択ダイアログを表示して、CSVファイルを選択
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, "CSVファイルを選択", "", "CSV files (*.csv);;All files (*.*)"
        )

        if not file_path:
            return

        # CSVファイルを読み込み
        import polars as pl

        try:
            df = pl.read_csv(file_path)
            # インポートダイアログを表示
            import_dialog = TagDataImportDialog(source_df=df, service=self.tag_import_service, parent=self)
            import_dialog.exec_()
        except Exception as e:
            self.logger.error(f"Error during import: {e}", exc_info=True)
            self.on_service_error(str(e))

    @Slot(str)
    def on_service_error(self, error_message: str):
        """サービスからのエラーをステータスバーに表示"""
        self.logger.error(f"Service error: {error_message}")
        self.statusbar.showMessage(f"エラー: {error_message}", 5000)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    # ロギングの設定
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    try:
        current_dir = Path(__file__).parent
        project_root = current_dir.parent
        sys.path.insert(0, str(project_root))

        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        logger.info("Application started successfully")
        sys.exit(app.exec())

    except Exception as e:
        logger.error(f"Application failed to start: {e}", exc_info=True)
        QMessageBox.critical(
            QApplication.activeWindow() or None, "起動エラー", f"アプリケーションの起動に失敗しました: {e}"
        )
        sys.exit(1)
