"""`search_tags_bulk` の SQL 発行数が入力タグ数に比例しないことを検証する (Issue #148)。

bulk API でありながら user overlay の適用と cross-scope preferred の解決を行ごとに
行っていたため、350 タグで SQL 4,428 本 (12.6 本/タグ) が発行されていた。
発行数を捕捉し、入力を増やしても本数がほぼ増えないことを検証する。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
)

pytestmark = pytest.mark.db_tools

_FORMAT_ID = 1
_FORMAT_NAME = "danbooru"
_TOTAL_TAGS = 60


@pytest.fixture
def base_session_factory(tmp_path: Path) -> Callable[[], Session]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'base.sqlite'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def user_session_factory(tmp_path: Path) -> Callable[[], Session]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'user.sqlite'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    UserOverlayBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _tag_name(tag_id: int) -> str:
    return f"sample_{tag_id}"


@pytest.fixture
def populated_base(base_session_factory: Callable[[], Session]) -> None:
    with base_session_factory() as session:
        session.add(TagFormat(format_id=_FORMAT_ID, format_name=_FORMAT_NAME))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=_FORMAT_ID, type_id=0, type_name_id=1))
        for tag_id in range(1, _TOTAL_TAGS + 1):
            name = _tag_name(tag_id)
            session.add(Tag(tag_id=tag_id, source_tag=name, tag=name))
            session.add(
                TagStatus(
                    tag_id=tag_id,
                    format_id=_FORMAT_ID,
                    type_id=0,
                    alias=False,
                    preferred_tag_id=tag_id,
                    deprecated=False,
                )
            )
        session.commit()


@pytest.fixture
def populated_user(user_session_factory: Callable[[], Session]) -> None:
    """user overlay を非空にする (空だと overlay 経路が短絡してしまう)。"""
    user_tag_id = USER_TAG_ID_OFFSET + 1
    with user_session_factory() as session:
        session.add(UserTag(tag_id=user_tag_id, source_tag="user_only", tag="user_only"))
        session.flush()
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=user_tag_id,
                format_id=_FORMAT_ID,
                type_id=0,
                alias=False,
                preferred_scope="user",
                preferred_tag_id=user_tag_id,
                deprecated=False,
            )
        )
        session.commit()


@pytest.fixture
def merged(
    base_session_factory: Callable[[], Session],
    user_session_factory: Callable[[], Session],
    populated_base: None,
    populated_user: None,
) -> MergedTagReader:
    return MergedTagReader(
        base_repo=TagReader(session_factory=base_session_factory),
        user_repo=OverlayTagReader(session_factory=user_session_factory),
    )


def _count_statements(fn: Callable[[], object]) -> tuple[int, object]:
    """`fn` の実行中に発行された SQL 文の本数と戻り値を返す。"""
    count = 0

    def capture(conn, cursor, statement, parameters, context, executemany):
        nonlocal count
        count += 1

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        result = fn()
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    return count, result


def test_search_tags_bulk_query_count_does_not_scale_with_tag_count(
    merged: MergedTagReader,
) -> None:
    """入力タグ数を 5 倍にしても SQL 発行数がほぼ増えない (Issue #148)。

    修正前は user overlay 適用・cross-scope preferred 解決・format 名解決がすべて
    行ごとだったため、発行数が入力タグ数にほぼ比例していた。
    """
    few = [_tag_name(i) for i in range(1, 11)]  # 10 件
    many = [_tag_name(i) for i in range(1, 51)]  # 50 件

    # 同一 reader での 2 回目はキャッシュ差が出うるため、計測順の影響を避けて多い方を先に測る
    count_many, rows_many = _count_statements(
        lambda: merged.search_tags_bulk(many, format_name=_FORMAT_NAME, resolve_preferred=True)
    )
    count_few, rows_few = _count_statements(
        lambda: merged.search_tags_bulk(few, format_name=_FORMAT_NAME, resolve_preferred=True)
    )

    assert len(rows_few) == 10  # type: ignore[arg-type]
    assert len(rows_many) == 50  # type: ignore[arg-type]

    # 40 件増えても発行数の増加は定数本数に収まる (チャンク分割分のみ)
    assert count_many <= count_few + 5, (
        f"SQL 発行数が入力件数に比例している: 10 件={count_few} 本, 50 件={count_many} 本"
    )


def test_search_tags_bulk_matches_search_tags_per_keyword(merged: MergedTagReader) -> None:
    """バッチ化しても単数 `search_tags` と同じ行を返す (意味論の維持)。"""
    keywords = [_tag_name(i) for i in range(1, 21)]
    bulk = merged.search_tags_bulk(keywords, format_name=_FORMAT_NAME, resolve_preferred=True)

    for keyword in keywords:
        single = merged.search_tags(
            keyword, partial=False, format_name=_FORMAT_NAME, resolve_preferred=True
        )
        expected = single[0] if single else None
        actual = bulk.get(keyword)
        if expected is None:
            assert actual is None, f"{keyword}: bulk のみ行を返した"
            continue
        assert actual is not None, f"{keyword}: bulk が行を返していない"
        assert actual["tag_id"] == expected["tag_id"]
        assert actual.get("tag") == expected.get("tag")
