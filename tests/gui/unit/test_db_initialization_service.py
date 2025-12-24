"""DbInitializationService tests for async database initialization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from PySide6.QtCore import QCoreApplication

from genai_tag_db_tools.gui.services.db_initialization import DbInitWorker, DbInitializationService
from genai_tag_db_tools.models import DbCacheConfig, EnsureDbResult, DbSourceRef, EnsureDbRequest


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def sample_db_source():
    """Create sample database source."""
    return DbSourceRef(repo_id="test/repo", filename="test.sqlite")


@pytest.fixture
def sample_ensure_request(temp_cache_dir, sample_db_source):
    """Create sample ensure database request."""
    cache_config = DbCacheConfig(cache_dir=str(temp_cache_dir), token=None)
    return EnsureDbRequest(source=sample_db_source, cache=cache_config)


class TestDbInitWorker:
    """Tests for DbInitWorker."""

    def test_worker_initialization(self, sample_ensure_request, temp_cache_dir):
        """Worker should initialize with requests and cache dir."""
        worker = DbInitWorker(requests=[sample_ensure_request], cache_dir=temp_cache_dir)

        assert worker.requests == [sample_ensure_request]
        assert worker.cache_dir == temp_cache_dir
        assert worker.signals is not None

    @patch("genai_tag_db_tools.gui.services.db_initialization.ensure_databases")
    @patch("genai_tag_db_tools.gui.services.db_initialization.runtime")
    def test_worker_successful_initialization(
        self, mock_runtime, mock_ensure_databases, qtbot, sample_ensure_request, temp_cache_dir
    ):
        """Worker should emit complete signal on successful initialization."""
        # Mock ensure_databases to return success
        db_path = temp_cache_dir / "test.sqlite"
        db_path.touch()
        mock_ensure_databases.return_value = [
            EnsureDbResult(db_path=str(db_path), downloaded=True, from_cache=False)
        ]

        worker = DbInitWorker(requests=[sample_ensure_request], cache_dir=temp_cache_dir)

        # Track signal emissions
        progress_signals = []
        complete_signals = []
        error_signals = []

        worker.signals.progress.connect(lambda msg, pct: progress_signals.append((msg, pct)))
        worker.signals.complete.connect(lambda success, msg: complete_signals.append((success, msg)))
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        # Run worker
        worker.run()
        qtbot.wait(100)

        # Verify signals emitted
        assert len(progress_signals) >= 3  # At least 3 progress updates
        assert len(complete_signals) == 1
        assert complete_signals[0][0] is True  # success = True
        assert "Updated 1 database" in complete_signals[0][1]
        assert len(error_signals) == 0

        # Verify runtime methods called
        mock_runtime.set_base_database_paths.assert_called_once()
        mock_runtime.init_engine.assert_called_once()
        mock_runtime.init_user_db.assert_called_once_with(temp_cache_dir)

    @patch("genai_tag_db_tools.gui.services.db_initialization.ensure_databases")
    def test_worker_file_not_found_error(
        self, mock_ensure_databases, qtbot, sample_ensure_request, temp_cache_dir
    ):
        """Worker should emit error signal on FileNotFoundError."""
        mock_ensure_databases.side_effect = FileNotFoundError("Database file missing")

        worker = DbInitWorker(requests=[sample_ensure_request], cache_dir=temp_cache_dir)

        complete_signals = []
        error_signals = []

        worker.signals.complete.connect(lambda success, msg: complete_signals.append((success, msg)))
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        worker.run()
        qtbot.wait(100)

        # Verify error handling
        assert len(error_signals) == 1
        assert "Database file not found" in error_signals[0]
        assert len(complete_signals) == 1
        assert complete_signals[0][0] is False  # success = False

    @patch("genai_tag_db_tools.gui.services.db_initialization.ensure_databases")
    @patch("genai_tag_db_tools.gui.services.db_initialization.runtime")
    def test_worker_connection_error_with_cache(
        self, mock_runtime, mock_ensure_databases, qtbot, sample_ensure_request, temp_cache_dir
    ):
        """Worker should fallback to cache on ConnectionError."""
        mock_ensure_databases.side_effect = ConnectionError("Network unreachable")

        # Create cached database file
        base_db_dir = temp_cache_dir / "base_dbs"
        base_db_dir.mkdir()
        cached_db = base_db_dir / "test.sqlite"
        cached_db.touch()

        worker = DbInitWorker(requests=[sample_ensure_request], cache_dir=temp_cache_dir)

        complete_signals = []
        error_signals = []

        worker.signals.complete.connect(lambda success, msg: complete_signals.append((success, msg)))
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        worker.run()
        qtbot.wait(100)

        # Should succeed with cached database
        assert len(complete_signals) == 1
        assert complete_signals[0][0] is True
        assert "cached" in complete_signals[0][1].lower()

    @patch("genai_tag_db_tools.gui.services.db_initialization.ensure_databases")
    def test_worker_connection_error_without_cache(
        self, mock_ensure_databases, qtbot, sample_ensure_request, temp_cache_dir
    ):
        """Worker should fail if no cache available on ConnectionError."""
        mock_ensure_databases.side_effect = ConnectionError("Network unreachable")

        # No cached database files

        worker = DbInitWorker(requests=[sample_ensure_request], cache_dir=temp_cache_dir)

        complete_signals = []
        error_signals = []

        worker.signals.complete.connect(lambda success, msg: complete_signals.append((success, msg)))
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        worker.run()
        qtbot.wait(100)

        # Should fail
        assert len(error_signals) >= 1
        assert len(complete_signals) == 1
        assert complete_signals[0][0] is False


class TestDbInitializationService:
    """Tests for DbInitializationService."""

    def test_service_initialization_default_cache(self, qtbot):
        """Service should initialize with default cache directory."""
        service = DbInitializationService()
        qtbot.addWidget(service)

        assert service.cache_dir is not None
        assert isinstance(service.cache_dir, Path)
        assert service.thread_pool is not None

    def test_service_initialization_custom_cache(self, qtbot, temp_cache_dir):
        """Service should initialize with custom cache directory."""
        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        assert service.cache_dir == temp_cache_dir

    def test_default_sources(self, qtbot):
        """_default_sources should return list of database sources."""
        service = DbInitializationService()
        qtbot.addWidget(service)

        sources = service._default_sources()

        assert isinstance(sources, list)
        assert len(sources) >= 1
        assert all(isinstance(s, DbSourceRef) for s in sources)

    @patch("genai_tag_db_tools.gui.services.db_initialization.ensure_databases")
    @patch("genai_tag_db_tools.gui.services.db_initialization.runtime")
    def test_initialize_databases_async(
        self, mock_runtime, mock_ensure_databases, qtbot, temp_cache_dir, sample_db_source
    ):
        """initialize_databases should start async initialization."""
        # Mock successful database ensure
        db_path = temp_cache_dir / "test.sqlite"
        db_path.touch()
        mock_ensure_databases.return_value = [
            EnsureDbResult(db_path=str(db_path), downloaded=False, from_cache=True)
        ]

        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        # Track signal emissions
        progress_signals = []
        complete_signals = []

        service.progress_updated.connect(lambda msg, pct: progress_signals.append((msg, pct)))
        service.initialization_complete.connect(lambda success, msg: complete_signals.append((success, msg)))

        # Start initialization
        service.initialize_databases(sources=[sample_db_source])

        # Wait for worker to complete
        with qtbot.waitSignal(service.initialization_complete, timeout=5000):
            pass

        # Verify signals emitted
        assert len(progress_signals) >= 1
        assert len(complete_signals) == 1
        assert complete_signals[0][0] is True

    def test_initialize_databases_with_token(self, qtbot, temp_cache_dir, sample_db_source):
        """initialize_databases should pass token to cache config."""
        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        # We can't easily test the token is used without mocking more internals,
        # but we can verify the method accepts it
        service.initialize_databases(sources=[sample_db_source], token="test_token")

        # Should not raise exception
        qtbot.wait(100)

    def test_on_worker_progress(self, qtbot, temp_cache_dir):
        """_on_worker_progress should emit progress_updated signal."""
        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        progress_signals = []
        service.progress_updated.connect(lambda msg, pct: progress_signals.append((msg, pct)))

        # Simulate worker progress
        service._on_worker_progress("Test message", 50)

        assert len(progress_signals) == 1
        assert progress_signals[0] == ("Test message", 50)

    def test_on_worker_complete_success(self, qtbot, temp_cache_dir):
        """_on_worker_complete should emit initialization_complete signal."""
        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        complete_signals = []
        service.initialization_complete.connect(lambda success, msg: complete_signals.append((success, msg)))

        # Simulate successful completion
        service._on_worker_complete(True, "Initialization successful")

        assert len(complete_signals) == 1
        assert complete_signals[0] == (True, "Initialization successful")

    def test_on_worker_complete_failure(self, qtbot, temp_cache_dir):
        """_on_worker_complete should emit failure signal."""
        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        complete_signals = []
        service.initialization_complete.connect(lambda success, msg: complete_signals.append((success, msg)))

        # Simulate failed completion
        service._on_worker_complete(False, "Initialization failed")

        assert len(complete_signals) == 1
        assert complete_signals[0] == (False, "Initialization failed")

    def test_on_worker_error(self, qtbot, temp_cache_dir):
        """_on_worker_error should emit error_occurred signal."""
        service = DbInitializationService(cache_dir=temp_cache_dir)
        qtbot.addWidget(service)

        error_signals = []
        service.error_occurred.connect(lambda msg: error_signals.append(msg))

        # Simulate error
        service._on_worker_error("Test error message")

        assert len(error_signals) == 1
        assert error_signals[0] == "Test error message"
