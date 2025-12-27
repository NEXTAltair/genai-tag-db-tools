"""Database initialization service for GUI.

このモジュールは、GUIアプリケーションの起動時にHugging Faceから
データベースをダウンロードし、適切に初期化するための機能を提供します。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from genai_tag_db_tools.core_api import ensure_databases
from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.models import DbCacheConfig, DbSourceRef, EnsureDbRequest

logger = logging.getLogger(__name__)


class DbInitializationProgress(Protocol):
    """データベース初期化の進捗を通知するプロトコル。"""

    def on_progress(self, message: str, progress: int) -> None:
        """進捗通知。

        Args:
            message: 進捗メッセージ
            progress: 進捗率 (0-100)
        """
        ...

    def on_complete(self, success: bool, message: str) -> None:
        """完了通知。

        Args:
            success: 成功したかどうか
            message: 完了メッセージ
        """
        ...

    def on_error(self, error: str) -> None:
        """エラー通知。

        Args:
            error: エラーメッセージ
        """
        ...


class DbInitWorker(QRunnable):
    """データベース初期化を非同期実行するワーカー。"""

    class Signals(QObject):
        """ワーカー用シグナル定義。"""

        progress = Signal(str, int)  # (message, progress_percentage)
        complete = Signal(bool, str)  # (success, message)
        error = Signal(str)  # (error_message)

    def __init__(
        self,
        requests: list[EnsureDbRequest],
        user_db_dir: Path,
    ):
        """初期化。

        Args:
            requests: データベース準備リクエストのリスト
            user_db_dir: ユーザーDB配置ディレクトリ（明示的に指定）
        """
        super().__init__()
        self.requests = requests
        self.user_db_dir = user_db_dir
        self.signals = self.Signals()

    def run(self) -> None:
        """データベースのダウンロードと初期化を実行する。"""
        try:
            self.signals.progress.emit("Checking for database updates...", 10)

            # HFからデータベースをダウンロード/更新確認
            results = ensure_databases(self.requests)

            self.signals.progress.emit("Database files ready, initializing...", 50)

            # ベースDBパスを設定
            base_paths = [Path(result.db_path) for result in results]
            runtime.set_base_database_paths(base_paths)

            # ベースエンジン初期化
            runtime.init_engine(base_paths[0])

            self.signals.progress.emit("Initializing user database...", 70)
            runtime.init_user_db(self.user_db_dir)  # Use explicit parameter

            self.signals.progress.emit("Database initialization complete", 100)

            # Simplified message (downloaded field removed)
            if any(r.cached for r in results):
                message = "Database ready (offline mode)"
            else:
                message = "Database ready"

            self.signals.complete.emit(True, message)
            logger.info("Database initialization completed successfully")

        except FileNotFoundError as e:
            error_msg = f"Database file not found: {e}"
            logger.error(error_msg)
            self.signals.error.emit(error_msg)
            self.signals.complete.emit(False, error_msg)

        except Exception as e:
            error_msg = f"Unexpected error during initialization: {e}"
            logger.error(error_msg, exc_info=True)
            self.signals.error.emit(error_msg)
            self.signals.complete.emit(False, error_msg)


class DbInitializationService(QObject):
    """GUIアプリケーション向けのデータベース初期化サービス。

    このサービスは、起動時にHugging Faceからデータベースを取得し、
    適切に初期化する責務を持ちます。
    """

    progress_updated = Signal(str, int)  # (message, progress_percentage)
    initialization_complete = Signal(bool, str)  # (success, message)
    error_occurred = Signal(str)  # (error_message)

    def __init__(
        self,
        user_db_dir: Path | None = None,
        parent: QObject | None = None,
    ):
        """初期化。

        Args:
            user_db_dir: ユーザーDB配置ディレクトリ（Noneの場合はデフォルト）
            parent: 親QObject
        """
        super().__init__(parent)
        self.user_db_dir = user_db_dir or self._default_cache_dir()
        self.thread_pool = QThreadPool.globalInstance()
        logger.info("DbInitializationService initialized with user_db_dir=%s", self.user_db_dir)

    def _default_cache_dir(self) -> Path:
        """デフォルトのキャッシュディレクトリを取得。"""
        from genai_tag_db_tools.io.hf_downloader import default_cache_dir

        return default_cache_dir()

    def initialize_databases(
        self,
        sources: list[DbSourceRef] | None = None,
        token: str | None = None,
    ) -> None:
        """データベースの初期化を非同期で開始する。

        Args:
            sources: データベースソースのリスト（Noneの場合はデフォルト）
            token: Hugging Faceアクセストークン
        """
        if sources is None:
            sources = self._default_sources()

        cache_config = DbCacheConfig(
            cache_dir=str(self.user_db_dir),  # Repurposed as user_db_dir
            token=token,
        )

        requests = [EnsureDbRequest(source=source, cache=cache_config) for source in sources]

        worker = DbInitWorker(requests, self.user_db_dir)  # Pass explicit path
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.complete.connect(self._on_worker_complete)
        worker.signals.error.connect(self._on_worker_error)

        self.thread_pool.start(worker)
        logger.info("Database initialization started asynchronously")

    def _default_sources(self) -> list[DbSourceRef]:
        """デフォルトのデータベースソース一覧を取得。"""
        return [
            DbSourceRef(
                repo_id="NEXTAltair/genai-image-tag-db-CC4",
                filename="genai-image-tag-db-cc4.sqlite",
            ),
            DbSourceRef(
                repo_id="NEXTAltair/genai-image-tag-db-mit",
                filename="genai-image-tag-db-mit.sqlite",
            ),
            DbSourceRef(
                repo_id="NEXTAltair/genai-image-tag-db",
                filename="genai-image-tag-db-cc0.sqlite",
            ),
        ]

    @Slot(str, int)
    def _on_worker_progress(self, message: str, progress: int) -> None:
        """ワーカーからの進捗通知を転送。"""
        logger.debug("Init progress: %s (%d%%)", message, progress)
        self.progress_updated.emit(message, progress)

    @Slot(bool, str)
    def _on_worker_complete(self, success: bool, message: str) -> None:
        """ワーカーからの完了通知を転送。"""
        if success:
            logger.info("Database initialization successful: %s", message)
        else:
            logger.error("Database initialization failed: %s", message)
        self.initialization_complete.emit(success, message)

    @Slot(str)
    def _on_worker_error(self, error: str) -> None:
        """ワーカーからのエラー通知を転送。"""
        logger.error("Database initialization error: %s", error)
        self.error_occurred.emit(error)
