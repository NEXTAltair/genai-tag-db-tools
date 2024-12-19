import pytest
import polars as pl
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from pathlib import Path
from typing import Optional

@pytest.fixture(scope="function")
def engine():
    """テスト用に SQLite インメモリ データベースを作成"""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    return engine

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
