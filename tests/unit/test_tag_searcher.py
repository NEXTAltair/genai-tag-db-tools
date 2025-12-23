from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.db.schema import Base, TagFormat, TagTypeFormatMapping, TagTypeName
from genai_tag_db_tools.services.tag_search import TagSearcher

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


def _seed_format_and_type(session: Session, *, format_id: int = 1, type_id: int = 0) -> None:
    session.add(TagFormat(format_id=format_id, format_name="test"))
    session.add(TagTypeName(type_name_id=type_id, type_name="general"))
    session.add(TagTypeFormatMapping(format_id=format_id, type_id=type_id, type_name_id=type_id))
    session.commit()


def test_search_tags_filters_by_format_type_language(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    searcher = TagSearcher(repo)

    tag_id = repo.create_tag("alpha", "alpha")
    with session_factory() as session:
        _seed_format_and_type(session)

    repo.update_tag_status(tag_id, format_id=1, alias=False, preferred_tag_id=tag_id, type_id=0)
    repo.update_usage_count(tag_id, format_id=1, count=10)
    repo.add_or_update_translation(tag_id, language="ja", translation="alpha_ja")

    df = searcher.search_tags(
        "alpha",
        format_name="test",
        type_name="general",
        language="ja",
        min_usage=5,
        max_usage=20,
        alias=False,
    )

    assert isinstance(df, pl.DataFrame)
    assert df.height == 1
    assert df["tag"][0] == "alpha"
    assert df["alias"][0] is False
    assert df["usage_count"][0] == 10
    row = df.to_dicts()[0]
    assert row["translations"]["ja"] == ["alpha_ja"]


def test_convert_tag_resolves_alias(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    searcher = TagSearcher(repo)

    preferred_id = repo.create_tag("new_tag", "new_tag")
    alias_id = repo.create_tag("old_tag", "old_tag")
    invalid_id = repo.create_tag("invalid tag", "invalid tag")
    bad_id = repo.create_tag("bad_tag", "bad_tag")

    with session_factory() as session:
        _seed_format_and_type(session)

    repo.update_tag_status(alias_id, format_id=1, alias=True, preferred_tag_id=preferred_id, type_id=0)
    repo.update_tag_status(bad_id, format_id=1, alias=True, preferred_tag_id=invalid_id, type_id=0)

    assert searcher.convert_tag("old_tag", format_id=1) == "new_tag"
    assert searcher.convert_tag("bad_tag", format_id=1) == "bad_tag"


def test_get_formats_languages_types(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    searcher = TagSearcher(repo)

    tag_id = repo.create_tag("alpha", "alpha")
    with session_factory() as session:
        _seed_format_and_type(session)

    repo.update_tag_status(tag_id, format_id=1, alias=False, preferred_tag_id=tag_id, type_id=0)
    repo.add_or_update_translation(tag_id, language="ja", translation="alpha_ja")

    assert "test" in searcher.get_tag_formats()
    assert "ja" in searcher.get_tag_languages()
    assert "general" in searcher.get_tag_types("test")


def test_search_tags_resolve_preferred_replaces_tag_and_translations(
    session_factory: Callable[[], Session],
) -> None:
    repo = TagRepository(session_factory)
    searcher = TagSearcher(repo)

    preferred_id = repo.create_tag("new_tag", "new_tag")
    alias_id = repo.create_tag("old_tag", "old_tag")

    with session_factory() as session:
        _seed_format_and_type(session)

    repo.update_tag_status(alias_id, format_id=1, alias=True, preferred_tag_id=preferred_id, type_id=0)
    repo.update_tag_status(preferred_id, format_id=1, alias=False, preferred_tag_id=preferred_id, type_id=0)
    repo.add_or_update_translation(preferred_id, language="ja", translation="new_tag_ja")
    repo.add_or_update_translation(alias_id, language="ja", translation="old_tag_ja")

    df = searcher.search_tags(
        "old_tag",
        format_name="test",
        alias=True,
        resolve_preferred=True,
    )

    assert df.height == 1
    row = df.to_dicts()[0]
    assert row["tag"] == "new_tag"
    assert row["tag_id"] == preferred_id
    assert row["translations"]["ja"] == ["new_tag_ja"]
