import sys

from PySide6.QtWidgets import QApplication
from genai_tag_db_tools.gui.windows.main_window import MainWindow
from genai_tag_db_tools.services.tag_search import TagSearcher


def main():
    app = QApplication(sys.argv)
    tag_searcher = TagSearcher()
    window = MainWindow()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
