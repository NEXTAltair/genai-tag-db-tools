import logging
from pathlib import Path

from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.schema import Base

logger = logging.getLogger(__name__)


def _get_default_database_path() -> Path:
    """デフォルトのデータベースパスを返す。"""
    from genai_tag_db_tools.io.hf_downloader import default_cache_dir

    cache_dir = default_cache_dir()
    # デフォルトのファイル名(models.pyの例から)
    default_filename = "genai-image-tag-db-cc4.sqlite"

    # Hugging Face Hubのデフォルト保存先(local_dir使用時)
    # local_dir配下に直接ファイルが保存される
    return cache_dir / default_filename


_db_path: Path | None = None
_base_db_paths: list[Path] | None = None
_engine = None
_SessionLocal = None
_user_db_path: Path | None = None
_user_engine = None
_UserSessionLocal = None


def set_database_path(path: Path) -> None:
    """グローバルのDBパスを設定する。"""
    global _db_path, _base_db_paths
    _db_path = path
    _base_db_paths = [path]


def set_base_database_paths(paths: list[Path]) -> None:
    """複数ベースDBパスを設定する（優先順に並べる）。"""
    global _db_path, _base_db_paths
    if not paths:
        raise ValueError("paths は空にできません。")
    _base_db_paths = list(paths)
    _db_path = paths[0]


def get_database_path() -> Path:
    """設定済みのDBパスを返す。未設定ならデフォルト値を使用。"""
    if _db_path is None:
        default_path = _get_default_database_path()
        logger.info("DBパスが未設定のため、デフォルト値を使用: %s", default_path)
        return default_path
    return _db_path


def get_base_database_paths() -> list[Path]:
    """ベースDBパス一覧を返す。未設定なら単一DBを返す。"""
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


def init_user_db(cache_dir: Path) -> Path:
    """ユーザーDBを初期化する。存在しなければ空DBを作成する。"""
    global _user_db_path, _user_engine, _UserSessionLocal
    user_db_path = cache_dir / "user_db" / "user_tags.sqlite"
    user_db_path.parent.mkdir(parents=True, exist_ok=True)

    _user_db_path = user_db_path
    _user_engine = _create_engine(user_db_path)
    Base.metadata.create_all(_user_engine)
    _UserSessionLocal = sessionmaker(bind=_user_engine, autoflush=False, autocommit=False)
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
