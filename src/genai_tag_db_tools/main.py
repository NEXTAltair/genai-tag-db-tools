import sys

from genai_tag_db_tools.cli import build_parser
from genai_tag_db_tools.cli import main as cli_main


def _build_entry_parser():
    parser = build_parser()
    parser.add_argument("--gui", action="store_true", help="Launch the Qt GUI explicitly.")
    return parser


def _run_gui(argv: list[str] | None = None) -> None:
    app_argv = [sys.argv[0], *(argv or [])]

    from PySide6.QtWidgets import QApplication

    from genai_tag_db_tools.gui.windows.main_window import MainWindow

    app = QApplication(app_argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        _build_entry_parser().print_help()
        return

    if args in (["-h"], ["--help"]):
        _build_entry_parser().print_help()
        return

    if args[0] == "--gui":
        _run_gui(args[1:])
        return

    cli_main(args)


if __name__ == "__main__":
    main()
