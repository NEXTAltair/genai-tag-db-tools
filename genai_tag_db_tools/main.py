import sys

from PySide6.QtWidgets import QApplication
from genai_tag_db_tools.gui.windows.main_window import MainWindow
from genai_tag_db_tools.core.tag_search import initialize_tag_searcher


def main():
    app = QApplication(sys.argv)
    tag_searcher = initialize_tag_searcher()
    window = MainWindow()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
