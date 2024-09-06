import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget
from MainWindow_ui import Ui_MainWindow

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.init_widgets()
        self.setWindowTitle("タグデータベースツール")

    def init_widgets(self):
        self.tag_searcher = initialize_tag_searcher()
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec())