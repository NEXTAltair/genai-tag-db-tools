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
        cache_dir: Path,
    ):
        """初期化。

        Args:
            requests: データベース準備リクエストのリスト
            cache_dir: キャッシュディレクトリのパス（user_db など関連ファイルを配置）
        """
        super().__init__()
        self.requests = requests
        self.cache_dir = cache_dir
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
            runtime.init_user_db(self.cache_dir)

            self.signals.progress.emit("Database initialization complete", 100)

            downloaded_count = sum(1 for r in results if r.downloaded)
            if downloaded_count > 0:
                message = f"Updated {downloaded_count} database(s) from Hugging Face"
            else:
                message = "Using cached databases"

            self.signals.complete.emit(True, message)
            logger.info("Database initialization completed successfully")

        except FileNotFoundError as e:
            error_msg = f"Database file not found: {e}"
            logger.error(error_msg)
            self.signals.error.emit(error_msg)
            self.signals.complete.emit(False, error_msg)

        except ConnectionError as e:
            error_msg = f"Network error: {e}. Using cached database if available."
            logger.warning(error_msg)
            # オフライン時はキャッシュを使用
            try:
                base_paths = [
                    Path(req.cache.cache_dir) / "base_dbs" / req.source.filename for req in self.requests
                ]
                if all(p.exists() for p in base_paths):
                    runtime.set_base_database_paths(base_paths)
                    runtime.init_engine(base_paths[0])
                    runtime.init_user_db(self.cache_dir)
                    self.signals.complete.emit(True, "Using cached databases")
                else:
                    self.signals.error.emit("No cached base databases available")
                    self.signals.complete.emit(False, "Base databases unavailable")
            except Exception as fallback_error:
                logger.error("Fallback to cache failed: %s", fallback_error)
                self.signals.error.emit(str(fallback_error))
                self.signals.complete.emit(False, str(fallback_error))

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
        cache_dir: Path | None = None,
        parent: QObject | None = None,
    ):
        """初期化。

        Args:
            cache_dir: キャッシュディレクトリ（Noneの場合はデフォルト）
            parent: 親QObject
        """
        super().__init__(parent)
        self.cache_dir = cache_dir or self._default_cache_dir()
        self.thread_pool = QThreadPool.globalInstance()
        logger.info("DbInitializationService initialized with cache_dir=%s", self.cache_dir)

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
            cache_dir=str(self.cache_dir),
            token=token,
        )

        requests = [EnsureDbRequest(source=source, cache=cache_config) for source in sources]

        worker = DbInitWorker(requests, self.cache_dir)
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
