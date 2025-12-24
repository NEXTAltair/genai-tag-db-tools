# genai_tag_db_tools/gui/services/worker_service.py

"""Non-blocking async task management for GUI operations using Qt's QThreadPool."""

import logging
from collections.abc import Callable

import polars as pl
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from genai_tag_db_tools.models import TagSearchRequest
from genai_tag_db_tools.services.app_services import TagSearchService


class WorkerSignals(QObject):
    """Signal definitions for async workers."""

    finished = Signal(object)  # Result data
    error = Signal(str)  # Error message
    progress = Signal(int, str)  # (percentage, message)


class TagSearchWorker(QRunnable):
    """非同期タグ検索 Worker."""

    def __init__(self, service: TagSearchService, request: TagSearchRequest):
        """Initialize search worker.

        Args:
            service: Tag search service instance
            request: Search parameters
        """
        super().__init__()
        self.service = service
        self.request = request
        self.signals = WorkerSignals()
        self.logger = logging.getLogger(self.__class__.__name__)

    @Slot()
    def run(self) -> None:
        """Execute search in background thread."""
        try:
            self.logger.info("Starting async tag search: %s", self.request.query)
            self.signals.progress.emit(10, "検索開始...")

            # Perform search through service layer
            df = self.service.search_tags(
                keyword=self.request.query,
                partial=True,  # Default to partial search
                format_name=self.request.format_names[0] if self.request.format_names else None,
                type_name=self.request.type_names[0] if self.request.type_names else None,
                limit=self.request.limit,
                offset=self.request.offset,
            )

            self.signals.progress.emit(90, "検索完了")
            self.signals.finished.emit(df)
            self.logger.info("Async tag search completed: %d results", len(df))

        except Exception as e:
            self.logger.exception("Error in async tag search")
            self.signals.error.emit(str(e))


class WorkerService(QObject):
    """Non-blocking async task management service for GUI operations."""

    def __init__(self, parent: QObject | None = None):
        """Initialize worker service.

        Args:
            parent: Parent QObject
        """
        super().__init__(parent)
        self.thread_pool = QThreadPool.globalInstance()
        self.logger = logging.getLogger(self.__class__.__name__)

        # Configure thread pool
        max_threads = self.thread_pool.maxThreadCount()
        self.logger.info("WorkerService initialized with %d threads", max_threads)

    def run_search(
        self,
        service: TagSearchService,
        request: TagSearchRequest,
        on_success: Callable[[pl.DataFrame], None],
        on_error: Callable[[str], None],
        on_progress: Callable[[int, str], None] | None = None,
    ) -> None:
        """Run async tag search operation.

        Args:
            service: Tag search service instance
            request: Search parameters
            on_success: Callback for successful completion with DataFrame result
            on_error: Callback for error with error message
            on_progress: Optional callback for progress updates (percentage, message)
        """
        worker = TagSearchWorker(service, request)

        # Connect signals
        worker.signals.finished.connect(on_success, Qt.ConnectionType.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.ConnectionType.QueuedConnection)

        if on_progress:
            worker.signals.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)

        # Start async execution
        self.thread_pool.start(worker)
        self.logger.debug("Started async search worker")

    def active_thread_count(self) -> int:
        """Get number of currently active worker threads.

        Returns:
            Number of active threads
        """
        return self.thread_pool.activeThreadCount()

    def wait_for_done(self, timeout_ms: int = 30000) -> bool:
        """Wait for all workers to complete.

        Args:
            timeout_ms: Maximum wait time in milliseconds

        Returns:
            True if all workers completed, False if timeout
        """
        return self.thread_pool.waitForDone(timeout_ms)

    def close(self) -> None:
        """Clean up worker service and wait for active workers."""
        self.logger.info("Closing WorkerService, waiting for %d active workers", self.active_thread_count())
        self.thread_pool.waitForDone(5000)  # Wait up to 5 seconds
