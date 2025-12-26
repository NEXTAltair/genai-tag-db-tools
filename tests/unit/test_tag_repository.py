from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.db.schema import Base, Tag, TagFormat, TagTranslation

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


def test_create_tag_returns_existing_id(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    first_id = repo.create_tag("witch", "witch")
    second_id = repo.create_tag("witch", "witch")
    assert first_id == second_id


def test_bulk_insert_tags_deduplicates_by_tag(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    df = pl.DataFrame(
        {
            "source_tag": ["a", "b", "a"],
            "tag": ["dup", "dup", "dup"],
        }
    )
    repo.bulk_insert_tags(df)

    with session_factory() as session:
        rows = session.query(Tag).all()
        assert len(rows) == 1
        assert rows[0].tag == "dup"


def test_get_tag_formats_returns_sorted_list(session_factory: Callable[[], Session]) -> None:
    """Test that get_tag_formats returns formats in alphabetical order."""
    repo = TagRepository(session_factory)

    with session_factory() as session:
        session.add(TagFormat(format_id=1, format_name="e621"))
        session.add(TagFormat(format_id=2, format_name="danbooru"))
        session.add(TagFormat(format_id=3, format_name="zerochan"))
        session.add(TagFormat(format_id=4, format_name="animepictures"))
        session.commit()

    formats = repo.get_tag_formats()

    assert formats == ["animepictures", "danbooru", "e621", "zerochan"]


def test_get_tag_languages_returns_sorted_list(session_factory: Callable[[], Session]) -> None:
    """Test that get_tag_languages returns languages in alphabetical order."""
    repo = TagRepository(session_factory)

    with session_factory() as session:
        tag = Tag(tag_id=1, tag="test", source_tag="test")
        session.add(tag)
        session.add(TagTranslation(tag_id=1, language="japanese", translation="テスト"))
        session.add(TagTranslation(tag_id=1, language="english", translation="test"))
        session.add(TagTranslation(tag_id=1, language="chinese", translation="测试"))
        session.commit()

    languages = repo.get_tag_languages()

    assert languages == ["chinese", "english", "japanese"]
