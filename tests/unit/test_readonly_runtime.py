"""Cached readonly initialization never downloads, creates, migrates or seeds."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import OperationalError

from genai_tag_db_tools import ReadOnlyDatabaseError, database_runtime_scope, initialize_databases
from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.db.schema import Base
from genai_tag_db_tools.models import DbSourceRef


@pytest.fixture
def cached_databases(tmp_path, monkeypatch):
    base = tmp_path / "base ? 日本語.sqlite"
    engine = create_engine(URL.create("sqlite", database=str(base)))
    Base.metadata.create_all(engine)
    engine.dispose()
    with database_runtime_scope():
        user = runtime.init_user_db(tmp_path / "user", format_name="Lorairo")
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", Mock(return_value=str(base)))
    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.ensure_databases",
        Mock(side_effect=AssertionError("download forbidden")),
    )
    return base, user


def initialize(user):
    return initialize_databases(
        user_db_dir=user.parent,
        sources=[DbSourceRef(repo_id="test/db", filename="base.sqlite")],
        read_only=True,
    )


def test_readonly_init_has_no_logical_writes_and_enforces_database_protection(
    cached_databases, monkeypatch
):
    base, user = cached_databases
    before = {path: path.read_bytes() for path in (base, user)}
    statements = []
    monkeypatch.setattr(Path, "mkdir", Mock(side_effect=AssertionError("mkdir forbidden")))
    monkeypatch.setattr("socket.socket.connect", Mock(side_effect=AssertionError("network forbidden")))

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        with database_runtime_scope():
            results = initialize(user)
            assert results[0].cached is True
            with runtime.get_user_session_factory()() as session:
                assert session.execute(text("SELECT COUNT(*) FROM USER_TAGS")).scalar_one() == 0
            for factory in [runtime.get_user_session_factory(), *runtime.get_base_session_factories()]:
                with factory() as session:
                    assert session.execute(text("PRAGMA query_only")).scalar_one() == 1
            assert not [
                sql
                for sql in statements
                if sql.split()[0].upper() in {"CREATE", "INSERT", "UPDATE", "DELETE", "ALTER"}
            ]
            for factory in [runtime.get_user_session_factory(), *runtime.get_base_session_factories()]:
                with factory() as session, pytest.raises(OperationalError, match="readonly"):
                    session.execute(text("CREATE TABLE forbidden (value TEXT)"))
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    assert {path: path.read_bytes() for path in (base, user)} == before


@pytest.mark.parametrize("state", ["missing", "empty", "old"])
def test_unprepared_user_database_is_preserved(cached_databases, state):
    _, user = cached_databases
    if state == "missing":
        user.unlink()
    elif state == "empty":
        user.write_bytes(b"")
    else:
        engine = create_engine(f"sqlite:///{user}")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE USER_TAGS"))
        engine.dispose()
    before = user.read_bytes() if user.exists() else None
    with database_runtime_scope(), pytest.raises(ReadOnlyDatabaseError):
        initialize(user)
    assert (user.read_bytes() if user.exists() else None) == before


def test_missing_cache_does_not_create_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", Mock(return_value=None))
    with database_runtime_scope(), pytest.raises(ReadOnlyDatabaseError, match="not cached"):
        initialize_databases(user_db_dir=tmp_path / "missing", read_only=True)
    assert list(tmp_path.iterdir()) == []


def test_nested_runtime_restores_readonly_policy(cached_databases, tmp_path):
    _, user = cached_databases
    with database_runtime_scope():
        initialize(user)
        old_factory = runtime.get_user_session_factory()
        with database_runtime_scope():
            runtime.init_user_db(tmp_path / "writable")
        assert runtime.get_user_session_factory() is old_factory
        with pytest.raises(ReadOnlyDatabaseError, match="forbidden"):
            runtime.init_user_db(tmp_path / "forbidden")
        assert not (tmp_path / "forbidden").exists()
