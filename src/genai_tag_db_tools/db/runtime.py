import logging
from pathlib import Path

from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.orm import sessionmaker

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
    """グローバルのDBパスを設定する（単一DB用）。"""
    set_base_database_paths([path])


def set_base_database_paths(paths: list[Path]) -> None:
    """複数ベースDBパスを設定する（優先順に並べる）。"""
    global _base_db_paths
    if not paths:
        raise ValueError("paths は空にできません。")
    _base_db_paths = list(paths)


def get_database_path() -> Path:
    """設定済みのDBパスを返す。未設定ならエラー。"""
    if _base_db_paths is None or not _base_db_paths:
        raise RuntimeError(
            "DBパスが未設定です。ensure_db() または set_database_path() を先に呼んでください。"
        )
    return _base_db_paths[0]


def get_base_database_paths() -> list[Path]:
    """ベースDBパス一覧を返す。未設定なら例外を投げる。"""
    if _base_db_paths is not None:
        return list(_base_db_paths)
    return [get_database_path()]


def enable_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _create_engine(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path.absolute()}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    event.listen(engine, "connect", enable_foreign_keys)
    return engine


def create_session_factory(db_path: Path):
    """指定DBパスからセッションファクトリを作成する。"""
    engine = _create_engine(db_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_engine(path: Path | None = None) -> None:
    """DBパスからグローバルのエンジン/セッションを初期化する。"""
    global _engine, _SessionLocal

    db_path = path or get_database_path()
    if not db_path.exists():
        raise FileNotFoundError(f"DBファイルが見つかりません: {db_path}")

    _engine = _create_engine(db_path)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_session_factory():
    """Session factoryを返す。"""
    if _SessionLocal is None:
        raise RuntimeError("セッションが未初期化です。init_engine() を先に呼んでください。")
    return _SessionLocal


def get_base_session_factories() -> list[sessionmaker]:
    """ベースDBのセッションファクトリ一覧を返す（優先順）。"""
    factories: list[sessionmaker] = []
    for path in get_base_database_paths():
        if not path.exists():
            raise FileNotFoundError(f"DBファイルが見つかりません: {path}")
        factories.append(create_session_factory(path))
    return factories


def init_user_db(user_db_dir: Path | None = None) -> Path:
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

    logger.info("User DB initialized: %s", user_db_path)
    return user_db_path


def get_user_session_factory():
    """ユーザーDBのSession factoryを返す。"""
    if _UserSessionLocal is None:
        raise RuntimeError("ユーザーDBが未初期化です。init_user_db() を先に呼んでください。")
    return _UserSessionLocal


def get_user_session_factory_optional():
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
