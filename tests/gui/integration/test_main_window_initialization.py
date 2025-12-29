"""MainWindow 統合テスト（非同期 DB 初期化とウィジェット統合）"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThreadPool

from genai_tag_db_tools.gui.services import db_initialization
from genai_tag_db_tools.gui.windows.main_window import MainWindow
from genai_tag_db_tools.models import EnsureDbResult


@pytest.fixture
def db_init_env(monkeypatch, tmp_path):
    """DbInitializationServiceを実体で動かしつつHFダウンロードを抑止する。"""
    db_paths = []
    for filename in (
        "genai-image-tag-db-cc4.sqlite",
        "genai-image-tag-db-mit.sqlite",
        "genai-image-tag-db-cc0.sqlite",
    ):
        path = tmp_path / filename
        path.touch()
        db_paths.append(path)

    results = [
        EnsureDbResult(db_path=str(path), sha256="mock", revision=None, cached=True) for path in db_paths
    ]

    monkeypatch.setattr(db_initialization, "ensure_databases", lambda requests: results)

    def run_sync(self, runnable):
        runnable.run()

    monkeypatch.setattr(QThreadPool, "start", run_sync)

    yield tmp_path

    from genai_tag_db_tools.db import runtime

    runtime.close_all()


@pytest.mark.db_tools
def test_main_window_initialization(qtbot, db_init_env):
    """MainWindow が正しく初期化される"""
    window = MainWindow(cache_dir=db_init_env)
    qtbot.addWidget(window)

    assert window.db_init_service is not None
    assert window.tag_search_service is not None
    assert window.tag_cleaner_service is not None
    assert window.tag_register_service is not None
    assert window.tag_statistics_service is not None


@pytest.mark.db_tools
def test_main_window_db_init_progress_updates_ui(qtbot, db_init_env):
    """DB 初期化の進捗が UI に反映される"""
    window = MainWindow(cache_dir=db_init_env)
    qtbot.addWidget(window)

    window._on_db_init_progress("Loading database...", 50)

    assert window.progress_dialog.value() == 50


@pytest.mark.db_tools
def test_main_window_db_init_complete_success(qtbot, db_init_env):
    """DB 初期化成功時にサービスが初期化される"""
    with (
        patch.object(MainWindow, "_initialize_services") as mock_init_services,
        patch.object(MainWindow, "_initialize_widgets") as mock_init_widgets,
        patch(
            "genai_tag_db_tools.gui.windows.main_window.DbInitializationService.initialize_databases"
        ) as mock_initialize,
    ):
        mock_initialize.return_value = None
        window = MainWindow(cache_dir=db_init_env)
        qtbot.addWidget(window)

        window._on_db_init_complete(True, "Database initialized successfully")

        mock_init_services.assert_called_once()
        mock_init_widgets.assert_called_once()


@pytest.mark.db_tools
def test_main_window_db_init_complete_failure(qtbot, db_init_env, monkeypatch):
    """DB 初期化失敗時にエラーメッセージを表示"""
    from PySide6.QtWidgets import QMessageBox

    mock_critical = MagicMock()
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    with patch(
        "genai_tag_db_tools.gui.windows.main_window.DbInitializationService.initialize_databases"
    ) as mock_initialize:
        mock_initialize.return_value = None
        window = MainWindow(cache_dir=db_init_env)
    qtbot.addWidget(window)

    window._on_db_init_complete(False, "Database initialization failed")

    mock_critical.assert_called_once()


@pytest.mark.db_tools
def test_main_window_initialize_services_creates_all_services(qtbot, db_init_env):
    """_initialize_services() で全サービスが作成される"""
    with (
        patch("genai_tag_db_tools.gui.windows.main_window.TagSearchService") as mock_search,
        patch("genai_tag_db_tools.gui.windows.main_window.TagCleanerService") as mock_cleaner,
        patch("genai_tag_db_tools.gui.windows.main_window.TagRegisterService") as mock_register,
        patch("genai_tag_db_tools.gui.windows.main_window.TagStatisticsService") as mock_statistics,
        patch(
            "genai_tag_db_tools.gui.windows.main_window.DbInitializationService.initialize_databases"
        ) as mock_initialize,
    ):
        mock_initialize.return_value = None
        window = MainWindow(cache_dir=db_init_env)
        qtbot.addWidget(window)

        window._initialize_services()

        mock_search.assert_called_once()
        mock_cleaner.assert_called_once()
        mock_register.assert_called_once()
        mock_statistics.assert_called_once()


@pytest.mark.db_tools
def test_main_window_initialize_widgets_injects_services(qtbot, db_init_env):
    """_initialize_widgets() でウィジェットにサービスが注入される"""
    with (
        patch("genai_tag_db_tools.gui.windows.main_window.TagSearchService"),
        patch("genai_tag_db_tools.gui.windows.main_window.TagCleanerService"),
        patch("genai_tag_db_tools.gui.windows.main_window.TagRegisterService"),
        patch("genai_tag_db_tools.gui.windows.main_window.TagStatisticsService"),
        patch(
            "genai_tag_db_tools.gui.windows.main_window.DbInitializationService.initialize_databases"
        ) as mock_initialize,
    ):
        mock_initialize.return_value = None
        window = MainWindow(cache_dir=db_init_env)
        qtbot.addWidget(window)
        window._initialize_services()
        window._initialize_widgets()

    # ウィジェットがサービスを持っていることを確認
    assert window.tagSearch._service is not None
    assert window.tagCleaner._cleaner_service is not None
    assert window.tagRegister.search_service is not None
    assert window.tagStatistics.service is not None


@pytest.mark.db_tools
def test_main_window_close_event_cleans_up_resources(qtbot, db_init_env):
    """closeEvent() でリソースがクリーンアップされる"""
    with (
        patch("genai_tag_db_tools.gui.windows.main_window.TagSearchService"),
        patch("genai_tag_db_tools.gui.windows.main_window.TagCleanerService"),
        patch("genai_tag_db_tools.gui.windows.main_window.TagRegisterService"),
        patch("genai_tag_db_tools.gui.windows.main_window.TagStatisticsService"),
        patch("genai_tag_db_tools.gui.windows.main_window.runtime") as mock_runtime,
        patch(
            "genai_tag_db_tools.gui.windows.main_window.DbInitializationService.initialize_databases"
        ) as mock_initialize,
    ):
        mock_initialize.return_value = None
        window = MainWindow(cache_dir=db_init_env)
        qtbot.addWidget(window)
        window._initialize_services()

        # close() メソッドをモック化
        window.tag_search_service.close = MagicMock()
        window.tag_cleaner_service.close = MagicMock()
        window.tag_register_service.close = MagicMock()
        window.tag_statistics_service.close = MagicMock()

        window.close()

        window.tag_search_service.close.assert_called_once()
        window.tag_cleaner_service.close.assert_called_once()
        window.tag_register_service.close.assert_called_once()
        window.tag_statistics_service.close.assert_called_once()
        mock_runtime.close_all.assert_called_once()


@pytest.mark.db_tools
def test_main_window_with_custom_cache_dir(qtbot, db_init_env):
    """カスタムキャッシュディレクトリで MainWindow を初期化できる"""
    cache_dir = db_init_env / "custom_cache"

    window = MainWindow(cache_dir=cache_dir)
    qtbot.addWidget(window)

    assert window.db_init_service.user_db_dir == cache_dir
