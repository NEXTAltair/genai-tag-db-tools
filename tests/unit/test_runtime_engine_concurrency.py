"""_create_engine() のマルチスレッド同時アクセス回帰テスト (Issue #116)。

`poolclass=StaticPool` を指定していた頃は、全セッションが単一の生 sqlite3
コネクションを共有し、複数スレッドから同時に SQL を発行すると
``sqlite3.InterfaceError: bad parameter or other API misuse`` が発生していた。

`_create_engine()` は常に実ファイル `Path` を受け取るため、SQLAlchemy 既定の
`QueuePool` (スレッドごとに独立したコネクションを払い出す) に任せることで
この競合を回避する。本テストは実ファイル SQLite DB に対して複数スレッドから
同時にセッションを発行し、例外なく完了することを検証する。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from genai_tag_db_tools.db.runtime import _create_engine
from genai_tag_db_tools.db.schema import Base, TagFormat

THREAD_COUNT = 8
ITERATIONS_PER_THREAD = 20


def test_create_engine_uses_default_queue_pool(tmp_path: Path) -> None:
    """_create_engine() が StaticPool を指定せず既定の QueuePool を使うこと。"""
    db_path = tmp_path / "pool_class.sqlite"
    engine = _create_engine(db_path)
    try:
        assert isinstance(engine.pool, QueuePool)
    finally:
        engine.dispose()


def test_concurrent_sessions_do_not_raise_interface_error(tmp_path: Path) -> None:
    """複数スレッドが実ファイルDBへ同時にセッションを発行しても例外が出ないこと。

    修正前 (StaticPool) では、全スレッドが単一の生 sqlite3 コネクションを
    共有するため、同時アクセス時に
    ``sqlite3.InterfaceError: bad parameter or other API misuse`` を再現できた。
    """
    db_path = tmp_path / "concurrent.sqlite"
    engine = _create_engine(db_path)
    Base.metadata.create_all(engine)

    with sessionmaker(bind=engine, autoflush=False, autocommit=False)() as setup_session:
        setup_session.add(TagFormat(format_id=1, format_name="danbooru"))
        setup_session.commit()

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(ITERATIONS_PER_THREAD):
                with session_factory() as session:
                    result = (
                        session.execute(
                            select(TagFormat.format_id).where(TagFormat.format_name.in_(["danbooru"]))
                        )
                        .scalars()
                        .all()
                    )
                    assert result == [1]
        except BaseException as exc:  # スレッド内例外を親スレッドで検知するため意図的に広く捕捉
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(THREAD_COUNT)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    engine.dispose()

    assert not any(thread.is_alive() for thread in threads), "スレッドがタイムアウトしました"
    if errors:
        pytest.fail(f"並行アクセス中に例外が発生しました: {errors!r}")


def test_query_abort_check_interrupts_running_query(tmp_path: Path) -> None:
    """set_query_abort_check 登録中は実行中クエリが OperationalError で中断される (LoRAIro #1206)。"""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from genai_tag_db_tools.db.runtime import set_query_abort_check

    db_path = tmp_path / "abort_check.sqlite"
    engine = _create_engine(db_path)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # progress handler が確実に呼ばれる長さの再帰クエリ (数百万 VM 命令)
    long_query = text(
        "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 3000000) "
        "SELECT count(*) FROM seq"
    )

    set_query_abort_check(lambda: True)
    try:
        with factory() as session:
            with pytest.raises(OperationalError):
                session.execute(long_query).scalar()
    finally:
        set_query_abort_check(None)
        engine.dispose()


def test_query_abort_check_noop_when_unregistered(tmp_path: Path) -> None:
    """判定関数未登録 (None) ならクエリは通常どおり完走する。"""
    from sqlalchemy import text

    from genai_tag_db_tools.db.runtime import set_query_abort_check

    db_path = tmp_path / "abort_noop.sqlite"
    engine = _create_engine(db_path)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    set_query_abort_check(None)
    try:
        with factory() as session:
            result = session.execute(
                text(
                    "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 10000) "
                    "SELECT count(*) FROM seq"
                )
            ).scalar()
        assert result == 10000
    finally:
        engine.dispose()


def test_create_engine_sets_busy_timeout(tmp_path: Path) -> None:
    """_create_engine() の接続は busy_timeout が設定される (LoRAIro #1239)。

    GUI (書き) と CLI/RefinementWorker (読み) が user_tags.sqlite を共有するため、
    瞬間的なロック競合を即時失敗させず待機させる必要がある。
    """
    from sqlalchemy import text

    from genai_tag_db_tools.db.runtime import _BUSY_TIMEOUT_MS

    db_path = tmp_path / "busy_timeout.sqlite"
    engine = _create_engine(db_path)
    try:
        with engine.connect() as connection:
            timeout = connection.execute(text("PRAGMA busy_timeout")).scalar()
        assert timeout == _BUSY_TIMEOUT_MS
    finally:
        engine.dispose()


def test_ensure_wal_journal_mode_persists_wal(tmp_path: Path) -> None:
    """_ensure_wal_journal_mode() が file-backed DB を WAL に切り替える (LoRAIro #1165/#1239)。"""
    from sqlalchemy import text

    from genai_tag_db_tools.db.runtime import _ensure_wal_journal_mode

    db_path = tmp_path / "wal_mode.sqlite"
    engine = _create_engine(db_path)
    Base.metadata.create_all(engine)
    try:
        _ensure_wal_journal_mode(engine)
        with engine.connect() as connection:
            mode = connection.execute(text("PRAGMA journal_mode")).scalar()
        assert str(mode).lower() == "wal"
    finally:
        engine.dispose()
