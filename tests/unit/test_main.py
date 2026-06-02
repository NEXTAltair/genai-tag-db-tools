from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

import genai_tag_db_tools.main as entrypoint


def test_no_args_prints_help_without_gui_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_import = __import__

    def fail_on_pyside(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("PySide6"):
            raise AssertionError("PySide6 must not be imported for no-arg help")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_on_pyside)

    entrypoint.main([])

    captured = capsys.readouterr()
    assert "usage: tag-db" in captured.out
    assert "--gui" in captured.out
    assert "search" in captured.out
    assert "stats" in captured.out


@pytest.mark.parametrize("help_arg", ["-h", "--help"])
def test_help_arg_prints_entry_help(help_arg: str, capsys: pytest.CaptureFixture[str]) -> None:
    entrypoint.main([help_arg])

    captured = capsys.readouterr()
    assert "usage: tag-db" in captured.out
    assert "--gui" in captured.out


def test_gui_flag_runs_gui_path(monkeypatch: pytest.MonkeyPatch) -> None:
    run_gui = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_gui", run_gui)

    entrypoint.main(["--gui"])

    run_gui.assert_called_once_with([])


def test_gui_flag_passes_remaining_qt_args(monkeypatch: pytest.MonkeyPatch) -> None:
    run_gui = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_gui", run_gui)

    entrypoint.main(["--gui", "-platform", "offscreen"])

    run_gui.assert_called_once_with(["-platform", "offscreen"])


def test_subcommand_delegates_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    cli_main = MagicMock()
    monkeypatch.setattr(entrypoint, "cli_main", cli_main)

    entrypoint.main(["search", "--query", "cat"])

    cli_main.assert_called_once_with(["search", "--query", "cat"])


def test_run_gui_creates_main_window(monkeypatch: pytest.MonkeyPatch) -> None:
    app = MagicMock()
    app.exec.return_value = 0
    qapplication = MagicMock(return_value=app)
    window = MagicMock()
    main_window = MagicMock(return_value=window)

    qtwidgets_module = ModuleType("PySide6.QtWidgets")
    qtwidgets_module.QApplication = qapplication
    pyside_module = ModuleType("PySide6")
    gui_window_module = ModuleType("genai_tag_db_tools.gui.windows.main_window")
    gui_window_module.MainWindow = main_window

    monkeypatch.setitem(sys.modules, "PySide6", pyside_module)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets_module)
    monkeypatch.setitem(sys.modules, "genai_tag_db_tools.gui.windows.main_window", gui_window_module)
    monkeypatch.setattr(sys, "argv", ["tag-db", "--gui"])
    monkeypatch.setattr(sys, "exit", MagicMock())

    entrypoint._run_gui(["-platform", "offscreen"])

    qapplication.assert_called_once_with(["tag-db", "-platform", "offscreen"])
    main_window.assert_called_once_with()
    window.show.assert_called_once_with()
    sys.exit.assert_called_once_with(0)


def test_module_main_delegates_to_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import genai_tag_db_tools.__main__ as module_entrypoint

    main = MagicMock()
    monkeypatch.setattr(module_entrypoint, "main", main)

    module_entrypoint.main()

    main.assert_called_once_with()
