import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from genai_tag_db_tools.db.schema import Base, UserOverlayBase

logger = logging.getLogger(__name__)


# Global state
_base_db_paths: list[Path] | None = None
_engine = None
_SessionLocal = None
_user_db_path: Path | None = None
_user_engine = None
_UserSessionLocal = None

# 実行中 SQL を中断させる判定関数 (ホストアプリが set_query_abort_check で登録)
_query_abort_check: Callable[[], bool] | None = None

# progress handler の呼び出し間隔 (SQLite VM 命令数)。小さいほど応答が速いが
# オーバーヘッドが増える。長時間クエリの協調キャンセル用途なので粗くてよい。
_PROGRESS_HANDLER_INTERVAL = 4000

# ロック競合時の待機上限 (ms)。GUI (書き) と CLI/RefinementWorker (読み) が
# user_tags.sqlite を共有するため、瞬間的な排他ロックを即時失敗させず待機させる
# (LoRAIro #1239)。LoRAIro 本体 DB (db_core.BUSY_TIMEOUT_MS) と同値。
_BUSY_TIMEOUT_MS = 30000


def set_query_abort_check(check: Callable[[], bool] | None) -> None:
    """実行中 SQL を中断させる判定関数を登録する (LoRAIro #1206)。

    登録した関数は SQLite の progress handler として一定 VM 命令ごとに
    **クエリを実行しているスレッド上で** 呼ばれ、True を返すとそのクエリは
    `OperationalError` ("interrupted") で中断される。長時間クエリを協調キャンセルで
    打ち切りたいホストアプリが、スレッドローカルなキャンセル状態を見る関数を渡す想定。

    Args:
        check: 中断すべきなら True を返す関数。None で解除。
    """
    global _query_abort_check
    _query_abort_check = check


def _progress_handler() -> int:
    """SQLite progress handler 本体。非 0 を返すと実行中クエリを中断する。"""
    check = _query_abort_check
    if check is not None and check():
        return 1
    return 0


def _install_progress_handler(dbapi_connection: Any, connection_record: Any) -> None:
    dbapi_connection.set_progress_handler(_progress_handler, _PROGRESS_HANDLER_INTERVAL)


def set_database_path(path: Path) -> None:
    """Set base DB paths for a single DB."""
    set_base_database_paths([path])


def set_base_database_paths(paths: list[Path]) -> None:
    """Set base DB paths in priority order."""
    global _base_db_paths
    if not paths:
        raise ValueError("paths must not be empty")
    _base_db_paths = list(paths)


def get_base_database_paths() -> list[Path]:
    """Return base DB paths. Raises if not configured."""
    if _base_db_paths is None or not _base_db_paths:
        raise RuntimeError(
            "Base DB paths are not configured. Call ensure_db() or set_database_path() first."
        )
    return list(_base_db_paths)


def enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def set_busy_timeout(dbapi_connection: Any, connection_record: Any) -> None:
    """接続ごとに busy_timeout を設定する (LoRAIro #1239)。

    busy_timeout はロック待機の設定であり WAL への切り替え (#1165 でクラッシュした
    per-connection ``PRAGMA journal_mode=WAL``) のような排他取得は伴わないため、
    接続ごとに設定して安全。foreign_keys とは独立に単独 cursor で設定する。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def _ensure_wal_journal_mode(engine: Engine) -> None:
    """file-backed DB に WAL journal mode を DB 準備時 1 回だけ永続化する (LoRAIro #1165)。

    journal_mode=WAL は DB ヘッダに永続化されるため接続ごとに設定する必要はない。
    毎接続で ``PRAGMA journal_mode=WAL`` を実行すると、GUI/CLI 併用 (9p bind mount) 時に
    その一瞬の排他取得が busy_timeout の効かないまま ``database is locked`` /
    ``disk I/O error`` になり接続セットアップがクラッシュする。そこで準備時に一度だけ
    設定し、既に WAL の場合は書き換え (ロック取得) を避けて読み取りだけで済ませる。

    Args:
        engine: 対象の SQLAlchemy エンジン。``:memory:`` DB では何もしない。
    """
    if ":memory:" in str(engine.url):
        return
    try:
        with engine.connect() as connection:
            current = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
            if current is not None and str(current).lower() == "wal":
                return
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    except SQLAlchemyError:
        logger.warning("Failed to set WAL journal mode at DB preparation", exc_info=True)


def _create_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path.absolute()}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    event.listen(engine, "connect", enable_foreign_keys)
    # ロック競合時に即時失敗させず待機する (GUI/CLI 併用、LoRAIro #1239)。
    event.listen(engine, "connect", set_busy_timeout)
    # 協調キャンセルで実行中 SQL を中断できるようにする (set_query_abort_check)。
    # 判定関数未登録時は None チェックのみで実質オーバーヘッドなし。
    event.listen(engine, "connect", _install_progress_handler)
    return engine


def create_session_factory(db_path: Path) -> sessionmaker[Session]:
    """指定DBパスからセッションファクトリを作成する。"""
    engine = _create_engine(db_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_engine(path: Path | None = None) -> None:
    """DBパスからグローバルのエンジン/セッションを初期化する。"""
    global _engine, _SessionLocal

    db_path = path or get_base_database_paths()[0]
    if not db_path.exists():
        raise FileNotFoundError(f"DBファイルが見つかりません: {db_path}")

    _engine = _create_engine(db_path)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_session_factory() -> sessionmaker[Session]:
    """Session factoryを返す。"""
    if _SessionLocal is None:
        raise RuntimeError("セッションが未初期化です。init_engine() を先に呼んでください。")
    return _SessionLocal


def get_base_session_factories() -> list[sessionmaker[Session]]:
    """ベースDBのセッションファクトリ一覧を返す（優先順）。"""
    factories: list[sessionmaker[Session]] = []
    for path in get_base_database_paths():
        if not path.exists():
            raise FileNotFoundError(f"DBファイルが見つかりません: {path}")
        factories.append(create_session_factory(path))
    return factories


def init_user_db(user_db_dir: Path | None = None, *, format_name: str | None = None) -> Path:
    """ユーザーDBを初期化する。存在しなければ空DBを作成する。

    Args:
        user_db_dir: ユーザーDB配置ディレクトリ（Noneの場合はデフォルト）

    Returns:
        Path: 初期化されたuser_tags.sqliteのパス
    """
    global _user_db_path, _user_engine, _UserSessionLocal

    if user_db_dir is None:
        from genai_tag_db_tools.io.hf_downloader import default_cache_dir

        user_db_dir = default_cache_dir()

    user_db_path = user_db_dir / "user_tags.sqlite"
    user_db_path.parent.mkdir(parents=True, exist_ok=True)

    _user_db_path = user_db_path
    _user_engine = _create_engine(user_db_path)

    # user_tags.sqlite は GUI (書き) と CLI/RefinementWorker (読み) が共有する唯一の
    # 書き込み先。WAL は writer/reader 同時アクセスの並行性を上げ、単独巨大ロックを
    # 避ける。per-connection ではなく DB 準備時に 1 回だけ設定する (#1165/#1239)。
    _ensure_wal_journal_mode(_user_engine)

    # overlay テーブルを先に作成してから legacy 移行を実行する。
    # 移行関数が USER_TAGS / USER_TAG_STATUS_PATCH 等への INSERT を行うため、
    # テーブルが存在しない状態で呼び出すと OperationalError になる。
    Base.metadata.create_all(_user_engine)  # 後方互換（空テーブル）、将来削除予定
    UserOverlayBase.metadata.create_all(_user_engine)  # overlay テーブル追加

    # 旧スキーマ検出 → 自動移行
    from genai_tag_db_tools.db.user_db_migration import detect_legacy_schema, migrate_legacy_to_overlay

    if detect_legacy_schema(_user_engine):
        migration_result = migrate_legacy_to_overlay(_user_engine, user_db_path, backup=True)
        logger.info("legacy user DB を overlay schema へ移行しました: %s", migration_result)
    _UserSessionLocal = sessionmaker(bind=_user_engine, autoflush=False, autocommit=False)

    _initialize_default_user_mappings(_UserSessionLocal, format_name=format_name)

    logger.info("User DB initialized: %s", user_db_path)
    return user_db_path


def _initialize_default_user_mappings(
    session_factory: sessionmaker[Session], *, format_name: str | None
) -> None:
    """Ensure default format/type mappings exist for user DB."""
    from genai_tag_db_tools.db.repository import TagReader, TagRepository
    from genai_tag_db_tools.db.schema import TagFormat

    reader = TagReader(session_factory=session_factory)
    repo = TagRepository(session_factory=session_factory, reader=reader)

    resolved_format_name = format_name or "tag-db"
    type_name = "unknown"

    # Ensure format and type exist.
    format_id = repo.create_format_if_not_exists(
        format_name=resolved_format_name,
        description="Default user format",
        reader=reader,
    )
    type_name_id = repo.create_type_name_if_not_exists(type_name=type_name)

    # Ensure format mapping for unknown uses type_id=0.
    repo.create_type_format_mapping_if_not_exists(
        format_id=format_id,
        type_id=0,
        type_name_id=type_name_id,
        description=f"Default mapping for {resolved_format_name}/{type_name}",
    )

    # 既存破損データの修復: 全フォーマットの重複マッピングをクリーンアップ
    with session_factory() as session:
        all_format_ids = [f.format_id for f in session.query(TagFormat.format_id).all()]
    for fid in all_format_ids:
        repo.cleanup_duplicate_type_mappings(fid)


def get_user_session_factory() -> sessionmaker[Session]:
    """ユーザーDBのSession factoryを返す。"""
    if _UserSessionLocal is None:
        raise RuntimeError("ユーザーDBが未初期化です。init_user_db() を先に呼んでください。")
    return _UserSessionLocal


def get_user_session_factory_optional() -> sessionmaker[Session] | None:
    """ユーザーDB未初期化ならNoneを返す。"""
    return _UserSessionLocal


def get_user_db_path() -> Path | None:
    """ユーザーDBパスを返す。未初期化ならNone。"""
    return _user_db_path


def close_all() -> None:
    """Dispose active engines and reset session factories."""
    global _engine, _SessionLocal, _user_engine, _UserSessionLocal

    if _engine is not None:
        _engine.dispose()
        _engine = None
    if _user_engine is not None:
        _user_engine.dispose()
        _user_engine = None

    _SessionLocal = None
    _UserSessionLocal = None
