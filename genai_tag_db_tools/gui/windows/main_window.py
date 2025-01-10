import sys
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QApplication, QMainWindow, QDialog
from genai_tag_db_tools.gui.designer.MainWindow_ui import Ui_MainWindow
from genai_tag_db_tools.gui.widgets.tag_search import TagSearchWidget
from genai_tag_db_tools.gui.widgets.tag_cleaner import TagCleanerWidget
from genai_tag_db_tools.gui.widgets.tag_import import TagDataImportDialog
from genai_tag_db_tools.gui.widgets.tag_register import TagRegisterWidget
from genai_tag_db_tools.gui.widgets.tag_statistics import TagStatisticsWidget


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        # 必要なサービスを初期化
        from genai_tag_db_tools.services.tag_search import TagSearcher
        from genai_tag_db_tools.services.app_services import TagSearchService, TagImportService

        self.tag_searcher = TagSearcher()
        self.tag_search_service = TagSearchService()
        self.tag_import_service = TagImportService()

        self.setupUi(self)  # まずUIをセットアップ
        self.init_widgets()  # その後でウィジェットを初期化
        self.setWindowTitle("タグデータベースツール")

    def initialize(self, tag_searcher):
        """後方互換性のために残す"""
        self.tag_searcher = tag_searcher

    def init_widgets(self):
        # Replace placeholder widgets with actual instances
        search_widget = TagSearchWidget(service=self.tag_search_service)
        search_widget.error_occurred.connect(self.on_service_error)
        self.tabWidget.removeTab(0)
        self.tabWidget.insertTab(0, search_widget, "タグ検索")
        self.tagSearch = search_widget

        cleaner_widget = TagCleanerWidget()
        self.tabWidget.removeTab(1)
        self.tabWidget.insertTab(1, cleaner_widget, "タグクリーナー")
        self.tagCleaner = cleaner_widget

        register_widget = TagRegisterWidget()
        self.tabWidget.removeTab(2)
        self.tabWidget.insertTab(2, register_widget, "登録")
        self.tagRegister = register_widget

        stats_widget = TagStatisticsWidget()
        self.tabWidget.removeTab(3)
        self.tabWidget.insertTab(3, stats_widget, "タグ統計")
        self.tagStatistics = stats_widget

    @Slot()
    def on_actionImport_triggered(self):
        """
        メニューやツールバー上の 'Import' アクションが押された時の処理
        """
        # ファイル選択ダイアログを表示して、CSVファイルを選択
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CSVファイルを選択",
            "",
            "CSV files (*.csv);;All files (*.*)"
        )

        if not file_path:
            return

        # CSVファイルを読み込み
        import polars as pl
        try:
            df = pl.read_csv(file_path)
            # インポートダイアログを表示
            import_dialog = TagDataImportDialog(
                source_df=df,
                service=self.tag_import_service,
                parent=self
            )
            import_dialog.exec_()
        except Exception as e:
            self.on_service_error(str(e))

    def on_service_error(self, error_message: str):
        """サービスエラーをステータスバーに表示"""
        self.statusbar.showMessage(f"エラー: {error_message}", 5000)  # 5秒間表示


if __name__ == "__main__":
    import sys
    from pathlib import Path

    current_dir = Path(__file__).parent
    project_root = current_dir.parent
    sys.path.insert(0, str(project_root))
    from genai_tag_db_tools.services.tag_search import TagSearcher

    app = QApplication(sys.argv)
    tag_searcher = TagSearcher()
    window = MainWindow()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())
