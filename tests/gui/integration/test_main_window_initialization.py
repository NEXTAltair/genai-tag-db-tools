"""MainWindow 統合テスト（非同期 DB 初期化とウィジェット統合）"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt

from genai_tag_db_tools.gui.windows.main_window import MainWindow


@pytest.fixture
def mock_db_init_service(monkeypatch):
    """DbInitializationService をモック化"""
    with patch("genai_tag_db_tools.gui.windows.main_window.DbInitializationService") as mock:
        mock_instance = MagicMock()
        mock_instance.progress_updated = MagicMock()
        mock_instance.initialization_complete = MagicMock()
        mock_instance.error_occurred = MagicMock()
        mock_instance.initialize_databases = MagicMock()

        # connect() メソッドをモック化（Qt シグナル接続を無視）
        mock_instance.progress_updated.connect = MagicMock()
        mock_instance.initialization_complete.connect = MagicMock()
        mock_instance.error_occurred.connect = MagicMock()

        mock.return_value = mock_instance
        yield mock_instance


@pytest.mark.db_tools
def test_main_window_initialization(qtbot, mock_db_init_service):
    """MainWindow が正しく初期化される"""
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.db_init_service is not None
    assert window.tag_search_service is None  # DB 初期化前は None
    assert window.tag_cleaner_service is None
    assert window.tag_register_service is None
    assert window.tag_statistics_service is None


@pytest.mark.db_tools
def test_main_window_connects_db_init_signals(qtbot, mock_db_init_service):
    """MainWindow が DB 初期化シグナルを接続する"""
    window = MainWindow()
    qtbot.addWidget(window)

    # シグナル接続が呼ばれたことを確認
    mock_db_init_service.progress_updated.connect.assert_called()
    mock_db_init_service.initialization_complete.connect.assert_called()
    mock_db_init_service.error_occurred.connect.assert_called()


@pytest.mark.db_tools
def test_main_window_starts_db_initialization(qtbot, mock_db_init_service):
    """MainWindow が DB 初期化を開始する"""
    window = MainWindow()
    qtbot.addWidget(window)

    mock_db_init_service.initialize_databases.assert_called_once()


@pytest.mark.db_tools
def test_main_window_db_init_progress_updates_ui(qtbot, mock_db_init_service):
    """DB 初期化の進捗が UI に反映される"""
    window = MainWindow()
    qtbot.addWidget(window)

    window._on_db_init_progress("Loading database...", 50)

    assert window.progress_dialog.value() == 50


@pytest.mark.db_tools
def test_main_window_db_init_complete_success(qtbot, mock_db_init_service):
    """DB 初期化成功時にサービスが初期化される"""
    with patch.object(MainWindow, "_initialize_services") as mock_init_services, patch.object(
        MainWindow, "_initialize_widgets"
    ) as mock_init_widgets:
        window = MainWindow()
        qtbot.addWidget(window)

        window._on_db_init_complete(True, "Database initialized successfully")

        mock_init_services.assert_called_once()
        mock_init_widgets.assert_called_once()


@pytest.mark.db_tools
def test_main_window_db_init_complete_failure(qtbot, mock_db_init_service, monkeypatch):
    """DB 初期化失敗時にエラーメッセージを表示"""
    from PySide6.QtWidgets import QMessageBox

    mock_critical = MagicMock()
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    window = MainWindow()
    qtbot.addWidget(window)

    window._on_db_init_complete(False, "Database initialization failed")

    mock_critical.assert_called_once()


@pytest.mark.db_tools
def test_main_window_initialize_services_creates_all_services(qtbot, mock_db_init_service):
    """_initialize_services() で全サービスが作成される"""
    with patch("genai_tag_db_tools.gui.windows.main_window.TagSearchService") as mock_search, patch(
        "genai_tag_db_tools.gui.windows.main_window.TagCleanerService"
    ) as mock_cleaner, patch(
        "genai_tag_db_tools.gui.windows.main_window.TagRegisterService"
    ) as mock_register, patch(
        "genai_tag_db_tools.gui.windows.main_window.TagStatisticsService"
    ) as mock_statistics:
        window = MainWindow()
        qtbot.addWidget(window)

        window._initialize_services()

        mock_search.assert_called_once()
        mock_cleaner.assert_called_once()
        mock_register.assert_called_once()
        mock_statistics.assert_called_once()


@pytest.mark.db_tools
def test_main_window_initialize_widgets_injects_services(qtbot, mock_db_init_service):
    """_initialize_widgets() でウィジェットにサービスが注入される"""
    window = MainWindow()
    qtbot.addWidget(window)

    # サービスを手動で設定（DB 初期化をスキップ）
    with patch("genai_tag_db_tools.gui.windows.main_window.TagSearchService"), patch(
        "genai_tag_db_tools.gui.windows.main_window.TagCleanerService"
    ), patch("genai_tag_db_tools.gui.windows.main_window.TagRegisterService"), patch(
        "genai_tag_db_tools.gui.windows.main_window.TagStatisticsService"
    ):
        window._initialize_services()
        window._initialize_widgets()

    # ウィジェットがサービスを持っていることを確認
    assert window.tagSearch._service is not None
    assert window.tagCleaner._cleaner_service is not None
    assert window.tagRegister.search_service is not None
    assert window.tagStatistics.service is not None


@pytest.mark.db_tools
def test_main_window_close_event_cleans_up_resources(qtbot, mock_db_init_service):
    """closeEvent() でリソースがクリーンアップされる"""
    with patch("genai_tag_db_tools.gui.windows.main_window.TagSearchService"), patch(
        "genai_tag_db_tools.gui.windows.main_window.TagCleanerService"
    ), patch("genai_tag_db_tools.gui.windows.main_window.TagRegisterService"), patch(
        "genai_tag_db_tools.gui.windows.main_window.TagStatisticsService"
    ), patch("genai_tag_db_tools.gui.windows.main_window.runtime") as mock_runtime:
        window = MainWindow()
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
def test_main_window_with_custom_cache_dir(qtbot, mock_db_init_service):
    """カスタムキャッシュディレクトリで MainWindow を初期化できる"""
    cache_dir = Path("/tmp/test_cache")

    window = MainWindow(cache_dir=cache_dir)
    qtbot.addWidget(window)

    # DbInitializationService が cache_dir 引数付きで呼ばれたことを確認
    from genai_tag_db_tools.gui.windows.main_window import DbInitializationService

    DbInitializationService.assert_called_with(cache_dir=cache_dir, parent=window)
