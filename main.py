import sys
from pathlib import Path
current_dir = Path(__file__).parent
project_root = current_dir / "gui"
sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication
from gui.MainWindow import MainWindow
from tag_search import initialize_tag_searcher

def main():
    app = QApplication(sys.argv)
    tag_searcher = initialize_tag_searcher()
    window = MainWindow()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":

    main()