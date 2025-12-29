import logging
import sys
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QProgressDialog

from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.gui.designer.MainWindow_ui import Ui_MainWindow
from genai_tag_db_tools.gui.services import (
    GuiTagRegisterService,
    TagCleanerService,
    TagSearchService,
    TagStatisticsService,
)
from genai_tag_db_tools.gui.services.db_initialization import DbInitializationService
from genai_tag_db_tools.gui.widgets.tag_cleaner import TagCleanerWidget
from genai_tag_db_tools.gui.widgets.tag_register import TagRegisterWidget
from genai_tag_db_tools.gui.widgets.tag_search import TagSearchWidget
from genai_tag_db_tools.gui.widgets.tag_statistics import TagStatisticsWidget


class MainWindow(QMainWindow, Ui_MainWindow):
    """Main GUI window for tag database tools.

    このウィンドウは、起動時にHugging Faceからデータベースをダウンロードし、
    core_api.pyを通じてタグデータベース機能を提供します。
    """

    def __init__(self, cache_dir: Path | None = None):
        """初期化。

        Args:
            cache_dir: データベースキャッシュディレクトリ
        """
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        try:
            # UI設定(DB初期化前に完了させる)
            self.setupUi(self)
            self.setWindowTitle("Tag Database Tools - Initializing...")

            # データベース初期化サービスを作成
            self.db_init_service = DbInitializationService(
                user_db_dir=cache_dir,
                parent=self,
            )
            self._connect_db_init_signals()

            # 進捗ダイアログを表示
            self.progress_dialog = QProgressDialog("Initializing database...", "", 0, 100, self)
            self.progress_dialog.setCancelButton(None)
            self.progress_dialog.setWindowTitle("Database Initialization")
            self.progress_dialog.setModal(True)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.setValue(0)

            # サービスとウィジェットは初期化完了後に設定
            self.tag_search_service: TagSearchService | None = None
            self.tag_cleaner_service: TagCleanerService | None = None
            self.tag_register_service: GuiTagRegisterService | None = None
            self.tag_statistics_service: TagStatisticsService | None = None

            # データベース初期化を開始
            self.db_init_service.initialize_databases()
            self.logger.info("MainWindow created, database initialization started")

        except Exception as e:
            self.logger.error("Error during MainWindow initialization: %s", e, exc_info=True)
            QMessageBox.critical(
                self,
                "Initialization Error",
                f"Application failed to initialize: {e}",
            )
            raise

    def _connect_db_init_signals(self) -> None:
        """データベース初期化サービスのシグナルを接続。"""
        self.db_init_service.progress_updated.connect(self._on_db_init_progress)
        self.db_init_service.initialization_complete.connect(self._on_db_init_complete)
        self.db_init_service.error_occurred.connect(self._on_db_init_error)

    @Slot(str, int)
    def _on_db_init_progress(self, message: str, progress: int) -> None:
        """データベース初期化の進捗を更新。"""
        self.progress_dialog.setLabelText(message)
        self.progress_dialog.setValue(progress)
        self.statusbar.showMessage(message)

    @Slot(bool, str)
    def _on_db_init_complete(self, success: bool, message: str) -> None:
        """データベース初期化完了時の処理。"""
        self.progress_dialog.close()

        if success:
            self.logger.info("Database initialized: %s", message)
            self.statusbar.showMessage(message, 5000)
            self.setWindowTitle("Tag Database Tools")

            # データベース初期化成功後にサービスを初期化
            try:
                self._initialize_services()
                self._initialize_widgets()
                self.logger.info("MainWindow initialization completed successfully")
            except Exception as e:
                self.logger.error("Error initializing services: %s", e, exc_info=True)
                QMessageBox.critical(
                    self,
                    "Service Initialization Error",
                    f"Failed to initialize services: {e}",
                )
        else:
            self.logger.error("Database initialization failed: %s", message)
            QMessageBox.critical(
                self,
                "Database Initialization Failed",
                f"Failed to initialize database: {message}",
            )
            self.setWindowTitle("Tag Database Tools")
            self.statusbar.showMessage(message, 10000)

    @Slot(str)
    def _on_db_init_error(self, error: str) -> None:
        """データベース初期化エラー時の処理。"""
        self.logger.error("Database initialization error: %s", error)
        self.statusbar.showMessage(f"Error: {error}", 10000)

    def _initialize_services(self) -> None:
        """サービスを初期化する(DB初期化完了後に呼ばれる)。"""
        self.tag_search_service = TagSearchService()
        self.tag_cleaner_service = TagCleanerService()
        self.tag_register_service = GuiTagRegisterService()
        self.tag_statistics_service = TagStatisticsService()
        self.logger.info("Services initialized successfully")

    def _initialize_widgets(self) -> None:
        """ウィジェットにサービスを注入する。"""
        if isinstance(self.tagSearch, TagSearchWidget):
            self.tagSearch.set_service(self.tag_search_service)

        if isinstance(self.tagCleaner, TagCleanerWidget):
            self.tagCleaner.set_service(self.tag_cleaner_service)

        if isinstance(self.tagRegister, TagRegisterWidget):
            self.tagRegister.set_services(self.tag_search_service, self.tag_register_service)

        if isinstance(self.tagStatistics, TagStatisticsWidget):
            self.tagStatistics.set_service(self.tag_statistics_service)

        self.logger.info("All widgets initialized successfully")

    def closeEvent(self, event: QCloseEvent) -> None:
        """アプリ終了時のクリーンアップ処理。

        Args:
            event: Close event
        """
        self.logger.info("Closing application and cleaning up resources")

        # サービスのクローズ
        if hasattr(self, "tag_search_service") and self.tag_search_service:
            self.tag_search_service.close()
        if hasattr(self, "tag_register_service") and self.tag_register_service:
            self.tag_register_service.close()
        if hasattr(self, "tag_statistics_service") and self.tag_statistics_service:
            self.tag_statistics_service.close()
        if hasattr(self, "tag_cleaner_service") and self.tag_cleaner_service:
            self.tag_cleaner_service.close()

        # DB エンジンのクローズ
        try:
            runtime.close_all()
            self.logger.info("Database engines closed")
        except Exception as e:
            self.logger.warning("Error closing database engines: %s", e)

        super().closeEvent(event)


if __name__ == "__main__":
    from pathlib import Path

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
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
        logger.error("Application failed to start: %s", e, exc_info=True)
        QMessageBox.critical(
            QApplication.activeWindow() or None,
            "Startup Error",
            f"Application failed to start: {e}",
        )
        sys.exit(1)
