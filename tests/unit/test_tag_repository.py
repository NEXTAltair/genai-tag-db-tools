from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
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
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))
    first_id = repo.create_tag("witch", "witch")
    second_id = repo.create_tag("witch", "witch")
    assert first_id == second_id


def test_bulk_insert_tags_deduplicates_by_tag(session_factory: Callable[[], Session]) -> None:
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))
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
    repo = TagReader(session_factory)

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
    repo = TagReader(session_factory)

    with session_factory() as session:
        tag = Tag(tag_id=1, tag="test", source_tag="test")
        session.add(tag)
        session.add(TagTranslation(tag_id=1, language="japanese", translation="テスト"))
        session.add(TagTranslation(tag_id=1, language="english", translation="test"))
        session.add(TagTranslation(tag_id=1, language="chinese", translation="测试"))
        session.commit()

    languages = repo.get_tag_languages()

    assert languages == ["chinese", "english", "japanese"]


def test_get_next_type_id_returns_zero_for_empty_format(session_factory: Callable[[], Session]) -> None:
    """Test that get_next_type_id returns 0 when no mappings exist for the format."""
    repo = TagRepository(session_factory)

    next_type_id = repo.get_next_type_id(format_id=1000)

    assert next_type_id == 0


def test_get_next_type_id_returns_incremented_value(session_factory: Callable[[], Session]) -> None:
    """Test that get_next_type_id returns max(type_id) + 1 when mappings exist."""
    from genai_tag_db_tools.db.schema import TagFormat, TagTypeName, TagTypeFormatMapping

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create format and type_name
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(TagTypeName(type_name_id=1, type_name="character"))
        session.add(TagTypeName(type_name_id=2, type_name="general"))

        # Create existing mappings: type_id 0, 1, 2
        session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=1, type_name_id=2))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=2, type_name_id=1))
        session.commit()

    next_type_id = repo.get_next_type_id(format_id=1000)

    assert next_type_id == 3  # max(0, 1, 2) + 1


def test_get_next_type_id_handles_multiple_formats_independently(
    session_factory: Callable[[], Session]
) -> None:
    """Test that get_next_type_id handles multiple formats independently."""
    from genai_tag_db_tools.db.schema import TagFormat, TagTypeName, TagTypeFormatMapping

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create two formats
        session.add(TagFormat(format_id=1000, format_name="Format1"))
        session.add(TagFormat(format_id=1001, format_name="Format2"))
        session.add(TagTypeName(type_name_id=1, type_name="test"))

        # Format 1000 has type_ids 0, 1
        session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=1, type_name_id=1))

        # Format 1001 has type_id 0 only
        session.add(TagTypeFormatMapping(format_id=1001, type_id=0, type_name_id=1))
        session.commit()

    next_type_id_1000 = repo.get_next_type_id(format_id=1000)
    next_type_id_1001 = repo.get_next_type_id(format_id=1001)

    assert next_type_id_1000 == 2  # max(0, 1) + 1 for format 1000
    assert next_type_id_1001 == 1  # max(0) + 1 for format 1001


def test_update_tags_type_batch_creates_type_names_and_mappings(
    session_factory: Callable[[], Session]
) -> None:
    """Test that update_tags_type_batch creates type_names and mappings as needed."""
    from genai_tag_db_tools.db.schema import TagFormat, Tag, TagStatus
    from genai_tag_db_tools.models import TagTypeUpdate

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create format and tags
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(Tag(tag_id=1, tag="witch", source_tag="witch"))
        session.add(Tag(tag_id=2, tag="mage", source_tag="mage"))
        session.add(
            TagStatus(tag_id=1, format_id=1000, type_id=0, alias=False, preferred_tag_id=1)
        )
        session.add(
            TagStatus(tag_id=2, format_id=1000, type_id=0, alias=False, preferred_tag_id=2)
        )
        session.commit()

    # Update tags with new type_names
    updates = [
        TagTypeUpdate(tag_id=1, type_name="character"),
        TagTypeUpdate(tag_id=2, type_name="general"),
    ]
    repo.update_tags_type_batch(updates, format_id=1000)

    # Verify type_names were created
    reader = TagReader(session_factory)
    all_types = reader.get_all_types()
    assert "character" in all_types
    assert "general" in all_types

    # Verify mappings were created with correct type_ids
    format_types = reader.get_tag_types(format_id=1000)
    assert "character" in format_types
    assert "general" in format_types

    # Verify tag statuses were updated
    with session_factory() as session:
        status1 = session.query(TagStatus).filter(TagStatus.tag_id == 1).first()
        status2 = session.query(TagStatus).filter(TagStatus.tag_id == 2).first()

        # type_id should be different for different type_names
        assert status1.type_id != status2.type_id
        assert status1.type_id in [0, 1]  # First two type_ids
        assert status2.type_id in [0, 1]


def test_update_tags_type_batch_reuses_existing_type_ids(
    session_factory: Callable[[], Session]
) -> None:
    """Test that update_tags_type_batch reuses existing type_ids for same type_name."""
    from genai_tag_db_tools.db.schema import (
        TagFormat,
        Tag,
        TagStatus,
        TagTypeName,
        TagTypeFormatMapping,
    )
    from genai_tag_db_tools.models import TagTypeUpdate

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create format, tags, and existing type mapping
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(TagTypeName(type_name_id=1, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))

        session.add(Tag(tag_id=1, tag="witch", source_tag="witch"))
        session.add(Tag(tag_id=2, tag="mage", source_tag="mage"))
        session.add(
            TagStatus(tag_id=1, format_id=1000, type_id=999, alias=False, preferred_tag_id=1)
        )
        session.add(
            TagStatus(tag_id=2, format_id=1000, type_id=999, alias=False, preferred_tag_id=2)
        )
        session.commit()

    # Update both tags with same type_name
    updates = [
        TagTypeUpdate(tag_id=1, type_name="character"),
        TagTypeUpdate(tag_id=2, type_name="character"),
    ]
    repo.update_tags_type_batch(updates, format_id=1000)

    # Verify both tags use the same type_id
    with session_factory() as session:
        status1 = session.query(TagStatus).filter(TagStatus.tag_id == 1).first()
        status2 = session.query(TagStatus).filter(TagStatus.tag_id == 2).first()

        assert status1.type_id == 0  # Existing mapping
        assert status2.type_id == 0  # Reused


def test_update_tags_type_batch_handles_empty_list(session_factory: Callable[[], Session]) -> None:
    """Test that update_tags_type_batch handles empty updates list gracefully."""
    repo = TagRepository(session_factory)

    # Should not raise any errors
    repo.update_tags_type_batch([], format_id=1000)


def test_update_tags_type_batch_auto_increments_type_ids(
    session_factory: Callable[[], Session]
) -> None:
    """Test that update_tags_type_batch auto-increments type_ids for multiple type_names."""
    from genai_tag_db_tools.db.schema import TagFormat, Tag, TagStatus
    from genai_tag_db_tools.models import TagTypeUpdate

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create format and tags
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(Tag(tag_id=1, tag="witch", source_tag="witch"))
        session.add(Tag(tag_id=2, tag="mage", source_tag="mage"))
        session.add(Tag(tag_id=3, tag="warrior", source_tag="warrior"))
        session.add(
            TagStatus(tag_id=1, format_id=1000, type_id=0, alias=False, preferred_tag_id=1)
        )
        session.add(
            TagStatus(tag_id=2, format_id=1000, type_id=0, alias=False, preferred_tag_id=2)
        )
        session.add(
            TagStatus(tag_id=3, format_id=1000, type_id=0, alias=False, preferred_tag_id=3)
        )
        session.commit()

    # Update tags with 3 different type_names
    updates = [
        TagTypeUpdate(tag_id=1, type_name="character"),
        TagTypeUpdate(tag_id=2, type_name="general"),
        TagTypeUpdate(tag_id=3, type_name="meta"),
    ]
    repo.update_tags_type_batch(updates, format_id=1000)

    # Verify all three type_names got different type_ids
    with session_factory() as session:
        status1 = session.query(TagStatus).filter(TagStatus.tag_id == 1).first()
        status2 = session.query(TagStatus).filter(TagStatus.tag_id == 2).first()
        status3 = session.query(TagStatus).filter(TagStatus.tag_id == 3).first()

        type_ids = {status1.type_id, status2.type_id, status3.type_id}
        assert len(type_ids) == 3  # All different
        assert type_ids == {0, 1, 2}  # Sequential allocation
