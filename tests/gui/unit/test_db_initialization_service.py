"""DbInitializationService tests for async database initialization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from genai_tag_db_tools.gui.services.db_initialization import DbInitializationService, DbInitWorker
from genai_tag_db_tools.models import DbSourceRef, EnsureDbResult


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


class TestDbInitWorker:
    """Tests for DbInitWorker."""

    def test_worker_initialization(self, sample_db_source, temp_cache_dir):
        """Worker should initialize with sources and user db dir."""
        worker = DbInitWorker(sources=[sample_db_source], user_db_dir=temp_cache_dir, token=None)

        assert worker.sources == [sample_db_source]
        assert worker.user_db_dir == temp_cache_dir
        assert worker.token is None
        assert worker.signals is not None

    @patch("genai_tag_db_tools.gui.services.db_initialization.initialize_databases")
    def test_worker_successful_initialization(
        self, mock_initialize, qtbot, sample_db_source, temp_cache_dir
    ):
        """Worker should emit complete signal on successful initialization."""
        # Mock initialize_databases to return success
        db_path = temp_cache_dir / "test.sqlite"
        db_path.touch()
        mock_initialize.return_value = [
            EnsureDbResult(db_path=str(db_path), sha256="test_hash", revision=None, cached=False)
        ]

        worker = DbInitWorker(
            sources=[sample_db_source],
            user_db_dir=temp_cache_dir,
            token=None,
        )

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
        assert "Database" in complete_signals[0][1]  # Message contains "Database"
        assert len(error_signals) == 0

        mock_initialize.assert_called_once_with(
            user_db_dir=temp_cache_dir,
            sources=[sample_db_source],
            token=None,
            init_user_db=True,
        )

    @patch("genai_tag_db_tools.gui.services.db_initialization.initialize_databases")
    def test_worker_file_not_found_error(self, mock_initialize, qtbot, sample_db_source, temp_cache_dir):
        """Worker should emit error signal on FileNotFoundError."""
        mock_initialize.side_effect = FileNotFoundError("Database file missing")

        worker = DbInitWorker(
            sources=[sample_db_source],
            user_db_dir=temp_cache_dir,
            token=None,
        )

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

    @patch("genai_tag_db_tools.gui.services.db_initialization.initialize_databases")
    def test_worker_connection_error_with_cache(
        self, mock_initialize, qtbot, sample_db_source, temp_cache_dir
    ):
        """Worker should emit error on ConnectionError."""
        mock_initialize.side_effect = ConnectionError("Network unreachable")

        worker = DbInitWorker(
            sources=[sample_db_source],
            user_db_dir=temp_cache_dir,
            token=None,
        )

        complete_signals = []
        error_signals = []

        worker.signals.complete.connect(lambda success, msg: complete_signals.append((success, msg)))
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        worker.run()
        qtbot.wait(100)

        # Should fail with error
        assert len(error_signals) >= 1
        assert len(complete_signals) == 1
        assert complete_signals[0][0] is False
        assert "Unexpected error during initialization" in complete_signals[0][1]

    @patch("genai_tag_db_tools.gui.services.db_initialization.initialize_databases")
    def test_worker_connection_error_without_cache(
        self, mock_initialize, qtbot, sample_db_source, temp_cache_dir
    ):
        """Worker should fail if no cache available on ConnectionError."""
        mock_initialize.side_effect = ConnectionError("Network unreachable")

        worker = DbInitWorker(
            sources=[sample_db_source],
            user_db_dir=temp_cache_dir,
            token=None,
        )

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
        """Service should initialize with default user db directory."""
        service = DbInitializationService()
        assert service.user_db_dir is not None
        assert isinstance(service.user_db_dir, Path)
        assert service.thread_pool is not None

    def test_service_initialization_custom_cache(self, qtbot, temp_cache_dir):
        """Service should initialize with custom user db directory."""
        service = DbInitializationService(user_db_dir=temp_cache_dir)
        assert service.user_db_dir == temp_cache_dir

    @patch("genai_tag_db_tools.gui.services.db_initialization.initialize_databases")
    def test_initialize_databases_async(self, mock_initialize, qtbot, temp_cache_dir, sample_db_source):
        """initialize_databases should start async initialization."""
        # Mock successful database ensure
        db_path = temp_cache_dir / "test.sqlite"
        db_path.touch()
        mock_initialize.return_value = [
            EnsureDbResult(db_path=str(db_path), sha256="test_hash", revision=None, cached=False)
        ]

        service = DbInitializationService(user_db_dir=temp_cache_dir)
        # Track signal emissions
        progress_signals = []
        complete_signals = []

        service.progress_updated.connect(lambda msg, pct: progress_signals.append((msg, pct)))
        service.initialization_complete.connect(
            lambda success, msg: complete_signals.append((success, msg))
        )

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
        service = DbInitializationService(user_db_dir=temp_cache_dir)
        # We can't easily test the token is used without mocking more internals,
        # but we can verify the method accepts it
        service.initialize_databases(sources=[sample_db_source], token="test_token")

        # Should not raise exception
        qtbot.wait(100)

    def test_on_worker_progress(self, qtbot, temp_cache_dir):
        """_on_worker_progress should emit progress_updated signal."""
        service = DbInitializationService(user_db_dir=temp_cache_dir)
        progress_signals = []
        service.progress_updated.connect(lambda msg, pct: progress_signals.append((msg, pct)))

        # Simulate worker progress
        service._on_worker_progress("Test message", 50)

        assert len(progress_signals) == 1
        assert progress_signals[0] == ("Test message", 50)

    def test_on_worker_complete_success(self, qtbot, temp_cache_dir):
        """_on_worker_complete should emit initialization_complete signal."""
        service = DbInitializationService(user_db_dir=temp_cache_dir)
        complete_signals = []
        service.initialization_complete.connect(
            lambda success, msg: complete_signals.append((success, msg))
        )

        # Simulate successful completion
        service._on_worker_complete(True, "Initialization successful")

        assert len(complete_signals) == 1
        assert complete_signals[0] == (True, "Initialization successful")

    def test_on_worker_complete_failure(self, qtbot, temp_cache_dir):
        """_on_worker_complete should emit failure signal."""
        service = DbInitializationService(user_db_dir=temp_cache_dir)
        complete_signals = []
        service.initialization_complete.connect(
            lambda success, msg: complete_signals.append((success, msg))
        )

        # Simulate failed completion
        service._on_worker_complete(False, "Initialization failed")

        assert len(complete_signals) == 1
        assert complete_signals[0] == (False, "Initialization failed")

    def test_on_worker_error(self, qtbot, temp_cache_dir):
        """_on_worker_error should emit error_occurred signal."""
        service = DbInitializationService(user_db_dir=temp_cache_dir)
        error_signals = []
        service.error_occurred.connect(lambda msg: error_signals.append(msg))

        # Simulate error
        service._on_worker_error("Test error message")

        assert len(error_signals) == 1
        assert error_signals[0] == "Test error message"
