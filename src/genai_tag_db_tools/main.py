import sys

from PySide6.QtWidgets import QApplication
from genai_tag_db_tools.gui.windows.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
