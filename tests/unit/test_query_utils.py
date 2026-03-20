from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.query_utils import TagSearchPreloader, TagSearchQueryBuilder
from genai_tag_db_tools.db.schema import (
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTypeFormatMapping,
    TagTypeName,
)

pytestmark = pytest.mark.db_tools


@pytest.fixture()
def session_factory() -> Callable[[], Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_minimal_schema(session: Session, total_tags: int) -> None:
    session.add(TagFormat(format_id=1, format_name="test"))
    session.add(TagTypeName(type_name_id=1, type_name="general"))
    session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
    for tag_id in range(1, total_tags + 1):
        tag_name = f"sample_{tag_id}"
        session.add(Tag(tag_id=tag_id, source_tag=tag_name, tag=tag_name))
        session.add(
            TagStatus(
                tag_id=tag_id,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=tag_id,
                deprecated=False,
            )
        )
    session.commit()


def test_initial_tag_ids_respects_limit_and_offset(session_factory: Callable[[], Session]) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=20)
        builder = TagSearchQueryBuilder(session)
        ids = builder.initial_tag_ids("%sample_%", use_like=True, limit=5, offset=3)
        assert len(ids) == 5


def test_preloader_load_handles_large_id_sets_with_chunking(
    session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLITE_IN_LIMIT を小さい値に上書きして、チャンク分割が正しく動作することを確認する。"""
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=1200)
        preloader = TagSearchPreloader(session)
        monkeypatch.setattr(preloader, "SQLITE_IN_LIMIT", 200)

        preloaded = preloader.load(set(range(1, 1201)))

        assert len(preloaded.tags_by_id) == 1200
        assert len(preloaded.statuses_by_tag_id) == 1200


def test_preloader_load_returns_empty_for_empty_input(session_factory: Callable[[], Session]) -> None:
    with session_factory() as session:
        preloader = TagSearchPreloader(session)
        preloaded = preloader.load(set())

    assert preloaded.tags_by_id == {}
    assert preloaded.statuses_by_tag_id == {}
