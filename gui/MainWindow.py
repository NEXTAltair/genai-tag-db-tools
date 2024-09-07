import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from MainWindow_ui import Ui_MainWindow
class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("タグデータベースツール")

    def initialize(self, tag_searcher):
        self.tag_searcher = tag_searcher
        self.init_widgets()

    def init_widgets(self):
        self.tagSearch.initialize(self.tag_searcher)
        self.tagClesner.initialize(self.tag_searcher)
        self.tagRegister.initialize(self.tag_searcher)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    current_dir = Path(__file__).parent
    project_root = current_dir.parent
    sys.path.insert(0, str(project_root))
    from tag_search import initialize_tag_searcher

    app = QApplication(sys.argv)
    tag_searcher = initialize_tag_searcher()
    window = MainWindow()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())