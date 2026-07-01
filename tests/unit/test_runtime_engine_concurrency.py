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
                    result = session.execute(
                        select(TagFormat.format_id).where(TagFormat.format_name.in_(["danbooru"]))
                    ).scalars().all()
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
