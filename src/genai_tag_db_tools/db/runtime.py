import logging
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, StaticPool, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from genai_tag_db_tools.db.schema import Base

logger = logging.getLogger(__name__)


# Global state
_base_db_paths: list[Path] | None = None
_engine = None
_SessionLocal = None
_user_db_path: Path | None = None
_user_engine = None
_UserSessionLocal = None


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


def _create_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path.absolute()}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    event.listen(engine, "connect", enable_foreign_keys)
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
    Base.metadata.create_all(_user_engine)
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
