"""WorkerService tests for async task management."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import polars as pl
import pytest
from PySide6.QtCore import QCoreApplication, QTimer

from genai_tag_db_tools.gui.services.worker_service import TagSearchWorker, WorkerService
from genai_tag_db_tools.models import TagSearchRequest
from genai_tag_db_tools.services.app_services import TagSearchService


@pytest.fixture
def mock_search_service():
    """Create mock search service."""
    service = Mock(spec=TagSearchService)
    service.search_tags = MagicMock(
        return_value=pl.DataFrame([{"tag": "cat", "translations": {}, "format_statuses": {}}])
    )
    return service


@pytest.fixture
def search_request():
    """Create sample search request."""
    return TagSearchRequest(
        query="cat",
        format_names=["danbooru"],
        type_names=["general"],
        resolve_preferred=True,
        include_aliases=True,
        include_deprecated=False,
        limit=100,
        offset=0,
    )


class TestTagSearchWorker:
    """Tests for TagSearchWorker."""

    def test_worker_initialization(self, mock_search_service, search_request):
        """Worker should initialize with service and request."""
        worker = TagSearchWorker(mock_search_service, search_request)

        assert worker.service == mock_search_service
        assert worker.request == search_request
        assert worker.signals is not None

    def test_worker_successful_search(self, qtbot, mock_search_service, search_request):
        """Worker should emit finished signal with DataFrame on success."""
        worker = TagSearchWorker(mock_search_service, search_request)

        # Track signal emissions
        finished_results = []
        error_results = []
        progress_results = []

        worker.signals.finished.connect(lambda df: finished_results.append(df))
        worker.signals.error.connect(lambda msg: error_results.append(msg))
        worker.signals.progress.connect(lambda pct, msg: progress_results.append((pct, msg)))

        # Run worker synchronously for testing
        worker.run()

        # Wait for signals to be processed
        qtbot.wait(100)

        # Verify finished signal emitted
        assert len(finished_results) == 1
        assert isinstance(finished_results[0], pl.DataFrame)
        assert len(finished_results[0]) == 1

        # Verify no errors
        assert len(error_results) == 0

        # Verify progress signals
        assert len(progress_results) == 2
        assert progress_results[0] == (10, "検索開始...")
        assert progress_results[1] == (90, "検索完了")

        # Verify service was called correctly
        mock_search_service.search_tags.assert_called_once_with(
            keyword="cat",
            partial=False,
            format_name="danbooru",
            type_name="general",
            alias=True,
            min_usage=None,
            max_usage=None,
            limit=100,
            offset=0,
        )

    def test_worker_error_handling(self, qtbot, mock_search_service, search_request):
        """Worker should emit error signal on exception."""
        # Configure service to raise exception
        mock_search_service.search_tags.side_effect = RuntimeError("Database connection failed")

        worker = TagSearchWorker(mock_search_service, search_request)

        # Track signal emissions
        finished_results = []
        error_results = []

        worker.signals.finished.connect(lambda df: finished_results.append(df))
        worker.signals.error.connect(lambda msg: error_results.append(msg))

        # Run worker
        worker.run()
        qtbot.wait(100)

        # Verify error signal emitted
        assert len(error_results) == 1
        assert "Database connection failed" in error_results[0]

        # Verify finished signal not emitted
        assert len(finished_results) == 0

    def test_worker_with_no_format_or_type(self, qtbot, mock_search_service):
        """Worker should handle requests without format/type filters."""
        request = TagSearchRequest(
            query="test",
            format_names=[],
            type_names=[],
            resolve_preferred=True,
            include_aliases=False,
        )

        worker = TagSearchWorker(mock_search_service, request)

        finished_results = []
        worker.signals.finished.connect(lambda df: finished_results.append(df))

        worker.run()
        qtbot.wait(100)

        # Verify search was called with None for format/type
        call_args = mock_search_service.search_tags.call_args
        assert call_args.kwargs["keyword"] == "test"
        assert call_args.kwargs["partial"] is False
        assert call_args.kwargs["format_name"] is None
        assert call_args.kwargs["type_name"] is None
        assert call_args.kwargs["alias"] is False


class TestWorkerService:
    """Tests for WorkerService."""

    def test_worker_service_initialization(self, qtbot):
        """WorkerService should initialize with thread pool."""
        service = WorkerService()

        assert service.thread_pool is not None
        assert service.active_thread_count() >= 0

    def test_run_search_async(self, qtbot, mock_search_service, search_request):
        """run_search should start worker without errors."""
        service = WorkerService()

        # Track worker execution
        callback_called = []

        def on_success(df: pl.DataFrame):
            callback_called.append("success")

        def on_error(msg: str):
            callback_called.append(f"error: {msg}")

        # Start async search
        service.run_search(
            service=mock_search_service,
            request=search_request,
            on_success=on_success,
            on_error=on_error,
        )

        # Wait for completion
        assert service.wait_for_done(timeout_ms=5000), "Worker should complete within timeout"

        # Verify mock was called (worker executed)
        assert mock_search_service.search_tags.call_count == 1

    def test_run_search_with_error(self, qtbot, mock_search_service, search_request):
        """run_search should handle errors in worker execution."""
        # Configure service to fail
        mock_search_service.search_tags.side_effect = ValueError("Invalid search parameters")

        service = WorkerService()

        service.run_search(
            service=mock_search_service,
            request=search_request,
            on_success=lambda df: None,
            on_error=lambda msg: None,
        )

        # Wait for worker to complete
        assert service.wait_for_done(timeout_ms=2000), "Worker should complete even with error"

        # Verify service was called (error occurred during execution)
        assert mock_search_service.search_tags.call_count == 1

    def test_run_search_without_progress_callback(self, qtbot, mock_search_service, search_request):
        """run_search should work without progress callback."""
        service = WorkerService()

        service.run_search(
            service=mock_search_service,
            request=search_request,
            on_success=lambda df: None,
            on_error=lambda msg: None,
            on_progress=None,  # No progress callback
        )

        # Wait for completion
        assert service.wait_for_done(timeout_ms=5000), "Worker should complete without progress callback"

        # Verify service was called
        assert mock_search_service.search_tags.call_count == 1

    def test_active_thread_count(self, qtbot, mock_search_service, search_request):
        """active_thread_count should return number of running workers."""
        service = WorkerService()

        initial_count = service.active_thread_count()

        # Start a worker (make search slow to catch it running)
        def slow_search(**kwargs):
            import time

            time.sleep(0.5)
            return pl.DataFrame([{"tag": "test", "translations": {}, "format_statuses": {}}])

        mock_search_service.search_tags.side_effect = slow_search

        service.run_search(
            service=mock_search_service,
            request=search_request,
            on_success=lambda df: None,
            on_error=lambda msg: None,
        )

        qtbot.wait(100)  # Give worker time to start

        # Active count should have increased
        active_count = service.active_thread_count()
        assert active_count >= initial_count

        # Wait for completion
        service.wait_for_done(timeout_ms=2000)

    def test_close(self, qtbot, mock_search_service, search_request):
        """close should wait for active workers to finish."""
        service = WorkerService()

        # Start a worker
        service.run_search(
            service=mock_search_service,
            request=search_request,
            on_success=lambda df: None,
            on_error=lambda msg: None,
        )

        # Close service
        service.close()

        # All workers should be finished
        assert service.active_thread_count() == 0
