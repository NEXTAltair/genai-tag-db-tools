import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

@pytest.fixture(scope="function")
def engine():
    """テスト用に SQLite インメモリ データベースを作成し、外部キー制約をONにする"""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    # SQLite の外部キー制約を有効化
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))

    yield engine

    # テスト終了後のクリーンアップ
    engine.dispose()

@pytest.fixture(scope="function")
def db_session(engine) -> Session:
    """テスト用に新しいデータベース セッションを作成"""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        yield session
    finally:
        session.rollback()
        transaction.rollback()
        connection.close()
