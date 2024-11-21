import pytest
import polars as pl
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from pathlib import Path
from typing import Optional

@pytest.fixture(scope="session")
def engine():
    """Create an SQLite in-memory database for testing"""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    return engine

@pytest.fixture(scope="function")
def db_session(engine) -> Session:
    """Create a new database session for a test"""
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
