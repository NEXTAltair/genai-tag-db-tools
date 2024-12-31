from pathlib import Path
from sqlalchemy import (
    create_engine,
    StaticPool,
)
from sqlalchemy.orm import sessionmaker

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v4.db")

engine = create_engine(
    f"sqlite:///{db_path.absolute()}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_session_factory():
    """
    コンテキストマネージャとして使いやすいように
    session_factoryを返すor with文で使える仕組みにする
    """
    return SessionLocal
