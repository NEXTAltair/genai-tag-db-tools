from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.query_utils import TagSearchPreloader
from genai_tag_db_tools.db.schema import Base, Tag, TagFormat, TagStatus, TagTypeFormatMapping, TagTypeName

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


def test_preloader_load_chunks_large_in_queries(session_factory: Callable[[], Session], monkeypatch) -> None:
    with session_factory() as session:
        session.add(TagFormat(format_id=1, format_name="test"))
        session.add(TagTypeName(type_name_id=0, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=0))
        for tag_id in range(1, 8):
            session.add(Tag(tag_id=tag_id, source_tag=f"s{tag_id}", tag=f"t{tag_id}"))
            session.add(
                TagStatus(
                    tag_id=tag_id,
                    format_id=1,
                    type_id=0,
                    alias=False,
                    preferred_tag_id=tag_id,
                )
            )
        session.commit()

    monkeypatch.setattr(TagSearchPreloader, "SQLITE_IN_LIMIT", 2)

    with session_factory() as session:
        preloader = TagSearchPreloader(session)
        loaded = preloader.load(set(range(1, 8)))

    assert len(loaded.tags_by_id) == 7
    assert len(loaded.status_by_tag_format) == 7
