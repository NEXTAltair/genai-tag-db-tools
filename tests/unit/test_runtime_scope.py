"""Public scoped runtime restores existing handles without reinitializing old databases."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from genai_tag_db_tools import database_runtime_scope
from genai_tag_db_tools.db import runtime


@pytest.fixture
def isolated_runtime():
    with database_runtime_scope():
        yield


def test_scope_restores_previous_runtime_without_old_database_writes(
    tmp_path, monkeypatch, isolated_runtime
):
    old_path = runtime.init_user_db(tmp_path / "old")
    old_factory = runtime.get_user_session_factory()
    old_engine = runtime._user_engine
    old_dispose = Mock(wraps=old_engine.dispose)
    monkeypatch.setattr(old_engine, "dispose", old_dispose)
    initialize = Mock(wraps=runtime.init_user_db)
    monkeypatch.setattr(runtime, "init_user_db", initialize)
    before = old_path.read_bytes()

    with database_runtime_scope():
        assert runtime.get_user_db_path() is None
        assert runtime.get_user_session_factory_optional() is None
        with pytest.raises(RuntimeError, match="not configured"):
            runtime.get_base_database_paths()
        runtime.init_user_db(tmp_path / "new")
        assert runtime.get_user_session_factory() is not old_factory

    assert runtime.get_user_db_path() == old_path
    assert runtime.get_user_session_factory() is old_factory
    assert old_path.read_bytes() == before
    initialize.assert_called_once_with(tmp_path / "new")
    old_dispose.assert_not_called()
    with old_factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_nested_scopes_and_error_restore_exact_handles(tmp_path, isolated_runtime):
    runtime.init_user_db(tmp_path / "outer")
    outer = runtime.get_user_session_factory()
    with database_runtime_scope():
        runtime.init_user_db(tmp_path / "middle")
        middle = runtime.get_user_session_factory()
        with pytest.raises(ValueError, match="operation failed"), database_runtime_scope():
            runtime.init_user_db(tmp_path / "inner")
            raise ValueError("operation failed")
        assert runtime.get_user_session_factory() is middle
    assert runtime.get_user_session_factory() is outer


def test_scope_disposes_all_engines_it_created(tmp_path, monkeypatch, isolated_runtime):
    disposers = []
    create = runtime.create_engine

    def create_tracked(*args, **kwargs):
        engine = create(*args, **kwargs)
        disposer = Mock(wraps=engine.dispose)
        disposers.append(disposer)
        monkeypatch.setattr(engine, "dispose", disposer)
        return engine

    monkeypatch.setattr(runtime, "create_engine", create_tracked)
    with database_runtime_scope():
        runtime.init_user_db(tmp_path / "one")
        runtime.init_user_db(tmp_path / "two")
        runtime.create_session_factory(tmp_path / "reader.sqlite")
    assert len(disposers) == 3
    for disposer in disposers:
        disposer.assert_called_once()
    assert runtime.get_user_session_factory_optional() is None
    assert runtime.get_user_db_path() is None


def test_cleanup_failure_still_restores_state_and_closes_other_engines(
    tmp_path, monkeypatch, isolated_runtime
):
    runtime.init_user_db(tmp_path / "old")
    old_factory = runtime.get_user_session_factory()
    with pytest.raises(ExceptionGroup, match="dispose scoped"), database_runtime_scope():
        runtime.init_user_db(tmp_path / "first")
        first_engine = runtime._user_engine
        real_dispose = first_engine.dispose
        monkeypatch.setattr(first_engine, "dispose", Mock(side_effect=RuntimeError("dispose failed")))
        runtime.init_user_db(tmp_path / "second")
        second_dispose = Mock(wraps=runtime._user_engine.dispose)
        monkeypatch.setattr(runtime._user_engine, "dispose", second_dispose)
    assert runtime.get_user_session_factory() is old_factory
    second_dispose.assert_called_once()
    real_dispose()


def test_threaded_scopes_serialize_without_crossing_databases(tmp_path):
    entered = Event()
    waiting = Event()
    release = Event()
    second_entered = Event()

    def first():
        with database_runtime_scope():
            runtime.init_user_db(tmp_path / "first")
            entered.set()
            assert release.wait(10)
            assert runtime.get_user_db_path() == tmp_path / "first" / "user_tags.sqlite"

    def second():
        assert entered.wait(10)
        waiting.set()
        with database_runtime_scope():
            second_entered.set()
            runtime.init_user_db(tmp_path / "second")
            assert runtime.get_user_db_path() == tmp_path / "second" / "user_tags.sqlite"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_job = pool.submit(first)
        second_job = pool.submit(second)
        try:
            assert entered.wait(10)
            assert waiting.wait(10)
            assert not second_entered.is_set()
        finally:
            release.set()
        first_job.result(timeout=10)
        second_job.result(timeout=10)
    assert second_entered.is_set()


def test_scope_restores_base_database_paths_and_factory(tmp_path, isolated_runtime):
    outer = tmp_path / "outer.sqlite"
    inner = tmp_path / "inner.sqlite"
    outer.touch()
    inner.touch()
    runtime.set_base_database_paths([outer])
    runtime.init_engine()
    original = runtime.get_session_factory()
    with database_runtime_scope():
        runtime.set_base_database_paths([inner])
        runtime.init_engine()
        assert runtime.get_base_database_paths() == [inner]
        assert runtime.get_session_factory() is not original
    assert runtime.get_base_database_paths() == [outer]
    assert runtime.get_session_factory() is original
    with original() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
