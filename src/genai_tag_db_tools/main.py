import sys

from genai_tag_db_tools.cli import main as cli_main


def main() -> None:
    if len(sys.argv) > 1:
        cli_main()
        return

    from PySide6.QtWidgets import QApplication

    from genai_tag_db_tools.gui.windows.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
