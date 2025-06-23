import sys
from collections.abc import Generator
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.data.database_schema import Base, TagDatabase


@pytest.fixture(scope="function")
def engine() -> Generator[Any, None, None]:
    """テスト用に SQLite インメモリ データベースを作成し、外部キー制約をONにする"""
    engine = create_engine(
        "sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # SQLite の外部キー制約を有効化
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))

    # データベーススキーマを作成
    Base.metadata.create_all(engine)

    yield engine

    # テスト終了後のクリーンアップ
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(engine) -> Generator[Session, None, None]:
    """テスト用に新しいデータベース セッションを作成"""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=engine)
    session = Session()

    # マスターデータを初期化
    TagDatabase(external_session=session, init_master=True)

    try:
        yield session
    finally:
        session.rollback()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="session")
def qapp():
    """ヘッドレスモードでQApplicationを起動する"""
    # ヘッドレスモードの設定
    if sys.platform.startswith("linux"):
        import os

        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication(sys.argv)
    yield app
    app.quit()
