from pathlib import Path

from sqlalchemy import (
    create_engine,
    StaticPool,
    event
)
from sqlalchemy.orm import sessionmaker

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v4.db")

def enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

engine = create_engine(
    f"sqlite:///{db_path.absolute()}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)

event.listen(engine, 'connect', enable_foreign_keys)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_session_factory():
    """
    コンテキストマネージャとして使いやすいように
    session_factoryを返すor with文で使える仕組みにする
    """
    return SessionLocal
