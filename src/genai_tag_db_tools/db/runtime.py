import logging
from pathlib import Path

from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.schema import Base

logger = logging.getLogger(__name__)

_db_path: Path | None = None
_engine = None
_SessionLocal = None


def set_database_path(path: Path) -> None:
    """グローバルのDBパスを設定する。"""
    global _db_path
    _db_path = path


def get_database_path() -> Path:
    """設定済みのDBパスを返す。未設定なら例外。"""
    if _db_path is None:
        raise RuntimeError("DBパスが未設定です。set_database_path() を先に呼んでください。")
    return _db_path


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


def init_user_db(cache_dir: Path) -> Path:
    """ユーザーDBを初期化する。存在しなければ空DBを作成する。"""
    user_db_path = cache_dir / "user_db" / "user_tags.sqlite"
    if user_db_path.exists():
        return user_db_path

    user_db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = _create_engine(user_db_path)
    Base.metadata.create_all(engine)
    return user_db_path
