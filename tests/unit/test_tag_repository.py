from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.schema import (
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
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


def test_search_tags_handles_large_candidate_set_without_sqlite_variable_overflow(
    session_factory: Callable[[], Session],
) -> None:
    """1000件超のタグが一致する検索で SQLite 変数上限エラーが発生しないことを確認するリグレッションテスト。"""
    reader = TagReader(session_factory)
    total_tags = 1200

    with session_factory() as session:
        session.add(TagFormat(format_id=1, format_name="test"))
        session.add(TagTypeName(type_name_id=0, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=0))

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
                )
            )
        session.commit()

    rows = reader.search_tags("sa", partial=True, format_name="test")
    assert len(rows) == total_tags


def test_get_next_type_id_returns_zero_for_empty_format(session_factory: Callable[[], Session]) -> None:
    """Test that get_next_type_id returns 0 when no mappings exist for the format."""
    repo = TagRepository(session_factory)

    next_type_id = repo.get_next_type_id(format_id=1000)

    assert next_type_id == 0


def test_get_next_type_id_returns_incremented_value(session_factory: Callable[[], Session]) -> None:
    """Test that get_next_type_id returns max(type_id) + 1 when mappings exist."""
    from genai_tag_db_tools.db.schema import TagFormat, TagTypeFormatMapping, TagTypeName

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
    session_factory: Callable[[], Session],
) -> None:
    """Test that get_next_type_id handles multiple formats independently."""
    from genai_tag_db_tools.db.schema import TagFormat, TagTypeFormatMapping, TagTypeName

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
    session_factory: Callable[[], Session],
) -> None:
    """Test that update_tags_type_batch creates type_names and mappings as needed."""
    from genai_tag_db_tools.db.schema import Tag, TagFormat, TagStatus
    from genai_tag_db_tools.models import TagTypeUpdate

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create format and tags
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(Tag(tag_id=1, tag="witch", source_tag="witch"))
        session.add(Tag(tag_id=2, tag="mage", source_tag="mage"))
        session.add(TagStatus(tag_id=1, format_id=1000, type_id=0, alias=False, preferred_tag_id=1))
        session.add(TagStatus(tag_id=2, format_id=1000, type_id=0, alias=False, preferred_tag_id=2))
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


def test_create_type_format_mapping_reuses_existing_type_name_mapping(
    session_factory: Callable[[], Session],
) -> None:
    """Test that same (format_id, type_name_id) returns existing type_id."""
    from genai_tag_db_tools.db.schema import TagFormat, TagTypeFormatMapping, TagTypeName

    repo = TagRepository(session_factory)

    with session_factory() as session:
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(TagTypeName(type_name_id=1, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=3, type_name_id=1))
        session.commit()

    resolved_type_id = repo.create_type_format_mapping_if_not_exists(
        format_id=1000,
        type_id=9,
        type_name_id=1,
    )

    assert resolved_type_id == 3
    with session_factory() as session:
        rows = (
            session.query(TagTypeFormatMapping)
            .filter(TagTypeFormatMapping.format_id == 1000, TagTypeFormatMapping.type_name_id == 1)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].type_id == 3


def test_create_type_format_mapping_resolves_type_id_collision(
    session_factory: Callable[[], Session],
) -> None:
    """Test that type_id collision for another type_name_id allocates next type_id."""
    from genai_tag_db_tools.db.schema import TagFormat, TagTypeFormatMapping, TagTypeName

    repo = TagRepository(session_factory)

    with session_factory() as session:
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(TagTypeName(type_name_id=1, type_name="character"))
        session.add(TagTypeName(type_name_id=2, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=1, type_name_id=1))
        session.commit()

    resolved_type_id = repo.create_type_format_mapping_if_not_exists(
        format_id=1000,
        type_id=1,
        type_name_id=2,
    )

    assert resolved_type_id == 2
    with session_factory() as session:
        rows = (
            session.query(TagTypeFormatMapping)
            .filter(TagTypeFormatMapping.format_id == 1000)
            .order_by(TagTypeFormatMapping.type_id)
            .all()
        )
        assert [(row.type_id, row.type_name_id) for row in rows] == [(1, 1), (2, 2)]


def test_update_tags_type_batch_reuses_existing_type_ids(session_factory: Callable[[], Session]) -> None:
    """Test that update_tags_type_batch reuses existing type_ids for same type_name."""
    from genai_tag_db_tools.db.schema import (
        Tag,
        TagFormat,
        TagStatus,
        TagTypeFormatMapping,
        TagTypeName,
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
        session.add(TagStatus(tag_id=1, format_id=1000, type_id=999, alias=False, preferred_tag_id=1))
        session.add(TagStatus(tag_id=2, format_id=1000, type_id=999, alias=False, preferred_tag_id=2))
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


def test_update_tags_type_batch_auto_increments_type_ids(session_factory: Callable[[], Session]) -> None:
    """Test that update_tags_type_batch auto-increments type_ids for multiple type_names."""
    from genai_tag_db_tools.db.schema import Tag, TagFormat, TagStatus
    from genai_tag_db_tools.models import TagTypeUpdate

    repo = TagRepository(session_factory)

    with session_factory() as session:
        # Create format and tags
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(Tag(tag_id=1, tag="witch", source_tag="witch"))
        session.add(Tag(tag_id=2, tag="mage", source_tag="mage"))
        session.add(Tag(tag_id=3, tag="warrior", source_tag="warrior"))
        session.add(TagStatus(tag_id=1, format_id=1000, type_id=0, alias=False, preferred_tag_id=1))
        session.add(TagStatus(tag_id=2, format_id=1000, type_id=0, alias=False, preferred_tag_id=2))
        session.add(TagStatus(tag_id=3, format_id=1000, type_id=0, alias=False, preferred_tag_id=3))
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


def test_get_unknown_type_tag_ids_returns_empty_when_no_unknown_type(
    session_factory: Callable[[], Session],
) -> None:
    """Test that get_unknown_type_tag_ids returns empty list when no unknown type exists."""
    from genai_tag_db_tools.db.schema import TagFormat

    reader = TagReader(session_factory)

    with session_factory() as session:
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.commit()

    # No unknown type exists
    result = reader.get_unknown_type_tag_ids(format_id=1000)
    assert result == []


def test_get_unknown_type_tag_ids_returns_tags_with_unknown_type(
    session_factory: Callable[[], Session],
) -> None:
    """Test that get_unknown_type_tag_ids returns tags with type_name='unknown'."""
    from genai_tag_db_tools.db.schema import (
        Tag,
        TagFormat,
        TagStatus,
        TagTypeFormatMapping,
        TagTypeName,
    )

    reader = TagReader(session_factory)

    with session_factory() as session:
        # Create format and unknown type
        session.add(TagFormat(format_id=1000, format_name="Test"))
        session.add(TagTypeName(type_name_id=1, type_name="unknown"))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))

        # Create tags with unknown type
        session.add(Tag(tag_id=10, tag="tag1", source_tag="tag1"))
        session.add(Tag(tag_id=11, tag="tag2", source_tag="tag2"))
        session.add(TagStatus(tag_id=10, format_id=1000, type_id=0, alias=False, preferred_tag_id=10))
        session.add(TagStatus(tag_id=11, format_id=1000, type_id=0, alias=False, preferred_tag_id=11))

        # Create tag with different type
        session.add(Tag(tag_id=12, tag="tag3", source_tag="tag3"))
        session.add(TagTypeName(type_name_id=2, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=1, type_name_id=2))
        session.add(TagStatus(tag_id=12, format_id=1000, type_id=1, alias=False, preferred_tag_id=12))

        session.commit()

    # Get unknown type tags
    result = reader.get_unknown_type_tag_ids(format_id=1000)
    assert sorted(result) == [10, 11]


def test_get_unknown_type_tag_ids_handles_multiple_formats(session_factory: Callable[[], Session]) -> None:
    """Test that get_unknown_type_tag_ids filters by format_id correctly."""
    from genai_tag_db_tools.db.schema import (
        Tag,
        TagFormat,
        TagStatus,
        TagTypeFormatMapping,
        TagTypeName,
    )

    reader = TagReader(session_factory)

    with session_factory() as session:
        # Create two formats with unknown type
        session.add(TagFormat(format_id=1000, format_name="Test1"))
        session.add(TagFormat(format_id=2000, format_name="Test2"))
        session.add(TagTypeName(type_name_id=1, type_name="unknown"))
        session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))
        session.add(TagTypeFormatMapping(format_id=2000, type_id=0, type_name_id=1))

        # Create tags for format 1000
        session.add(Tag(tag_id=10, tag="tag1", source_tag="tag1"))
        session.add(TagStatus(tag_id=10, format_id=1000, type_id=0, alias=False, preferred_tag_id=10))

        # Create tags for format 2000
        session.add(Tag(tag_id=20, tag="tag2", source_tag="tag2"))
        session.add(TagStatus(tag_id=20, format_id=2000, type_id=0, alias=False, preferred_tag_id=20))

        session.commit()

    # Get unknown type tags for format 1000 only
    result_1000 = reader.get_unknown_type_tag_ids(format_id=1000)
    assert result_1000 == [10]

    # Get unknown type tags for format 2000 only
    result_2000 = reader.get_unknown_type_tag_ids(format_id=2000)
    assert result_2000 == [20]


def test_get_translations_batch_returns_empty_for_empty_input(
    session_factory: Callable[[], Session],
) -> None:
    """空リスト入力時に空辞書を返すこと"""
    reader = TagReader(session_factory)
    assert reader.get_translations_batch([]) == {}


def test_get_translations_batch_returns_grouped_by_tag_id(
    session_factory: Callable[[], Session],
) -> None:
    """複数 tag_id の翻訳がまとめて取得され tag_id でグループ化されること"""
    reader = TagReader(session_factory)

    with session_factory() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(Tag(tag_id=2, tag="boy", source_tag="boy"))
        session.add(TagTranslation(tag_id=1, language="japanese", translation="女の子"))
        session.add(TagTranslation(tag_id=1, language="chinese", translation="女孩"))
        session.add(TagTranslation(tag_id=2, language="japanese", translation="男の子"))
        session.commit()

    result = reader.get_translations_batch([1, 2])

    assert 1 in result
    assert 2 in result
    ja_1 = next(tr for tr in result[1] if tr.language == "japanese")
    assert ja_1.translation == "女の子"
    zh_1 = next(tr for tr in result[1] if tr.language == "chinese")
    assert zh_1.translation == "女孩"
    ja_2 = next(tr for tr in result[2] if tr.language == "japanese")
    assert ja_2.translation == "男の子"


def test_get_translations_batch_ignores_unknown_tag_ids(
    session_factory: Callable[[], Session],
) -> None:
    """存在しない tag_id は結果辞書に含まれないこと"""
    reader = TagReader(session_factory)

    with session_factory() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(TagTranslation(tag_id=1, language="japanese", translation="女の子"))
        session.commit()

    result = reader.get_translations_batch([1, 999])

    assert 1 in result
    assert 999 not in result


def test_get_translations_batch_handles_sqlite_in_limit(
    session_factory: Callable[[], Session],
) -> None:
    """900件超の tag_ids でもチャンク分割して全件取得できること"""
    reader = TagReader(session_factory)
    total = 950

    with session_factory() as session:
        for tag_id in range(1, total + 1):
            session.add(Tag(tag_id=tag_id, tag=f"tag_{tag_id}", source_tag=f"tag_{tag_id}"))
            session.add(TagTranslation(tag_id=tag_id, language="japanese", translation=f"タグ{tag_id}"))
        session.commit()

    tag_ids = list(range(1, total + 1))
    result = reader.get_translations_batch(tag_ids)

    assert len(result) == total
    for tag_id in tag_ids:
        assert tag_id in result
        assert len(result[tag_id]) == 1


def test_merged_reader_get_translations_batch_deduplicates_across_repos(
    session_factory: Callable[[], Session],
) -> None:
    """複数 base_repo で同一 (language, translation) が重複しないこと"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine_b = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine_b)
    session_factory_b: Callable[[], Session] = sessionmaker(
        bind=engine_b, autoflush=False, autocommit=False
    )

    reader_a = TagReader(session_factory)
    reader_b = TagReader(session_factory_b)

    with session_factory() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(TagTranslation(tag_id=1, language="japanese", translation="女の子"))
        session.commit()

    with session_factory_b() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(TagTranslation(tag_id=1, language="japanese", translation="女の子"))
        session.commit()

    merged = MergedTagReader(base_repo=[reader_a, reader_b])
    result = merged.get_translations_batch([1])

    assert 1 in result
    assert len(result[1]) == 1
    assert result[1][0].translation == "女の子"


def test_get_usage_counts_batch_returns_empty_for_empty_input(
    session_factory: Callable[[], Session],
) -> None:
    """空リスト入力時に空辞書を返すこと"""
    reader = TagReader(session_factory)
    assert reader.get_usage_counts_batch([]) == {}


def test_get_usage_counts_batch_groups_by_tag_and_format(
    session_factory: Callable[[], Session],
) -> None:
    """複数 tag_id の使用回数が tag_id → {format_id: count} でグループ化されること"""
    reader = TagReader(session_factory)

    with session_factory() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(Tag(tag_id=2, tag="boy", source_tag="boy"))
        session.add(TagUsageCounts(tag_id=1, format_id=1, count=1234))
        session.add(TagUsageCounts(tag_id=1, format_id=2, count=42))
        session.add(TagUsageCounts(tag_id=2, format_id=1, count=7))
        session.commit()

    result = reader.get_usage_counts_batch([1, 2])

    assert result == {1: {1: 1234, 2: 42}, 2: {1: 7}}


def test_get_usage_counts_batch_ignores_unknown_tag_ids(
    session_factory: Callable[[], Session],
) -> None:
    """使用回数が無い tag_id は結果辞書に含まれないこと"""
    reader = TagReader(session_factory)

    with session_factory() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(TagUsageCounts(tag_id=1, format_id=1, count=10))
        session.commit()

    result = reader.get_usage_counts_batch([1, 999])

    assert 1 in result
    assert 999 not in result


def test_get_usage_counts_batch_handles_sqlite_in_limit(
    session_factory: Callable[[], Session],
) -> None:
    """900件超の tag_ids でもチャンク分割して全件取得できること"""
    reader = TagReader(session_factory)
    total = 950

    with session_factory() as session:
        for tag_id in range(1, total + 1):
            session.add(Tag(tag_id=tag_id, tag=f"tag_{tag_id}", source_tag=f"tag_{tag_id}"))
            session.add(TagUsageCounts(tag_id=tag_id, format_id=1, count=tag_id))
        session.commit()

    tag_ids = list(range(1, total + 1))
    result = reader.get_usage_counts_batch(tag_ids)

    assert len(result) == total
    assert result[total] == {1: total}


def test_merged_reader_get_usage_counts_batch_user_overrides_base(
    session_factory: Callable[[], Session],
) -> None:
    """user_repo の usage patch が base の (tag_id, format_id) を上書きすること"""
    from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
    from genai_tag_db_tools.db.schema import UserOverlayBase
    from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

    # base リポに使用回数を投入
    base_reader = TagReader(session_factory)
    with session_factory() as session:
        session.add(Tag(tag_id=1, tag="girl", source_tag="girl"))
        session.add(TagUsageCounts(tag_id=1, format_id=1, count=100))
        session.add(TagUsageCounts(tag_id=1, format_id=2, count=200))
        session.commit()

    # user overlay DB を別エンジンで用意し、format_id=1 を上書きする patch を書く
    user_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(user_engine)
    UserOverlayBase.metadata.create_all(user_engine)
    user_factory: Callable[[], Session] = sessionmaker(bind=user_engine, autoflush=False, autocommit=False)
    user_repo = UserTagRepository(user_factory)
    user_repo.write_usage_patch("base", 1, 1, 999)
    overlay = OverlayTagReader(session_factory=user_factory)

    merged = MergedTagReader(base_repo=base_reader, user_repo=overlay)
    result = merged.get_usage_counts_batch([1])

    # format_id=1 は user patch (999) で上書き、format_id=2 は base (200) のまま
    assert result == {1: {1: 999, 2: 200}}


def test_merged_reader_search_tags_applies_limit_after_merge(
    session_factory: Callable[[], Session],
) -> None:
    """複数DB検索でもmerge/dedup後にlimitを適用すること。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine_b = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine_b)
    session_factory_b: Callable[[], Session] = sessionmaker(
        bind=engine_b, autoflush=False, autocommit=False
    )

    reader_a = TagReader(session_factory)
    reader_b = TagReader(session_factory_b)

    with session_factory() as session:
        _seed_search_rows(session, range(1, 6))
    with session_factory_b() as session:
        _seed_search_rows(session, range(1, 6))

    merged = MergedTagReader(base_repo=[reader_a, reader_b])
    result = merged.search_tags("sample", partial=True, limit=3)

    assert [row["tag_id"] for row in result] == [1, 2, 3]


def test_merged_reader_search_tags_applies_offset_after_merge(
    session_factory: Callable[[], Session],
) -> None:
    """offsetはrepo別ではなくmerge済み結果に適用すること。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine_b = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine_b)
    session_factory_b: Callable[[], Session] = sessionmaker(
        bind=engine_b, autoflush=False, autocommit=False
    )

    reader_a = TagReader(session_factory)
    reader_b = TagReader(session_factory_b)

    with session_factory() as session:
        _seed_search_rows(session, range(1, 8))
    with session_factory_b() as session:
        _seed_search_rows(session, range(1, 8))

    merged = MergedTagReader(base_repo=[reader_a, reader_b])
    result = merged.search_tags("sample", partial=True, limit=2, offset=3)

    assert [row["tag_id"] for row in result] == [4, 5]


def _seed_bulk_all_rows(session: Session) -> None:
    """1 keyword が複数 tag_id にマッチする状況を作る (tag 直接一致 + 翻訳経由一致)。"""
    session.add(TagFormat(format_id=1, format_name="test"))
    session.add(TagTypeName(type_name_id=1, type_name="general"))
    session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
    # tag_id 1: "cat" に直接一致する canonical タグ
    session.add(Tag(tag_id=1, tag="cat", source_tag="cat"))
    session.add(
        TagStatus(tag_id=1, format_id=1, type_id=0, alias=False, preferred_tag_id=1, deprecated=False)
    )
    # tag_id 2: 別タグ "feline" だが翻訳 "cat" を持つ (keyword "cat" に翻訳経由で一致)
    session.add(Tag(tag_id=2, tag="feline", source_tag="feline"))
    session.add(
        TagStatus(tag_id=2, format_id=1, type_id=0, alias=False, preferred_tag_id=2, deprecated=False)
    )
    session.add(TagTranslation(tag_id=2, language="english", translation="cat"))
    session.commit()


def test_search_tags_bulk_all_returns_all_matching_rows(
    session_factory: Callable[[], Session],
) -> None:
    """search_tags_bulk_all は keyword ごとに全マッチ行を返す (bulk は最初の 1 行のみ)。"""
    reader = TagReader(session_factory)
    with session_factory() as session:
        _seed_bulk_all_rows(session)

    bulk = reader.search_tags_bulk(["cat"])
    all_rows = reader.search_tags_bulk_all(["cat"])

    # bulk は最小 tag_id の 1 行のみ
    assert bulk["cat"]["tag_id"] == 1
    # bulk_all は tag 直接一致 (1) と翻訳経由一致 (2) の両方を返す
    assert {row["tag_id"] for row in all_rows["cat"]} == {1, 2}


def test_search_tags_bulk_all_empty_and_no_match(
    session_factory: Callable[[], Session],
) -> None:
    """空入力・未一致 keyword は空 dict / キー欠落で返す。"""
    reader = TagReader(session_factory)
    with session_factory() as session:
        _seed_bulk_all_rows(session)

    assert reader.search_tags_bulk_all([]) == {}
    assert reader.search_tags_bulk_all(["nonexistent"]) == {}


def test_merged_reader_search_tags_bulk_all_merges_and_dedups(
    session_factory: Callable[[], Session],
) -> None:
    """複数 base DB の全マッチ行をマージし tag_id で dedup する。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine_b = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine_b)
    session_factory_b: Callable[[], Session] = sessionmaker(
        bind=engine_b, autoflush=False, autocommit=False
    )

    reader_a = TagReader(session_factory)
    reader_b = TagReader(session_factory_b)
    with session_factory() as session:
        _seed_bulk_all_rows(session)
    with session_factory_b() as session:
        _seed_bulk_all_rows(session)

    merged = MergedTagReader(base_repo=[reader_a, reader_b])
    result = merged.search_tags_bulk_all(["cat"])

    # 両 DB とも同一 tag_id 1,2 → dedup 後は tag_id 昇順で [1, 2] (search_tags と同じ順序)
    assert [row["tag_id"] for row in result["cat"]] == [1, 2]


def test_merged_reader_search_tags_bulk_all_higher_priority_db_wins(
    session_factory: Callable[[], Session],
) -> None:
    """同一 tag_id が複数 base DB にある場合、高優先度 (base_repos[0]) の行を採用する。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine_b = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine_b)
    session_factory_b: Callable[[], Session] = sessionmaker(
        bind=engine_b, autoflush=False, autocommit=False
    )

    def _seed_cat(session: Session, translation: str) -> None:
        session.add(TagFormat(format_id=1, format_name="test"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=1, tag="cat", source_tag="cat"))
        session.add(
            TagStatus(tag_id=1, format_id=1, type_id=0, alias=False, preferred_tag_id=1, deprecated=False)
        )
        session.add(TagTranslation(tag_id=1, language="japanese", translation=translation))
        session.commit()

    reader_a = TagReader(session_factory)
    reader_b = TagReader(session_factory_b)
    with session_factory() as session:
        _seed_cat(session, "猫A")  # 高優先度 (base_repos[0])
    with session_factory_b() as session:
        _seed_cat(session, "猫B")  # 低優先度

    merged = MergedTagReader(base_repo=[reader_a, reader_b])
    result = merged.search_tags_bulk_all(["cat"])

    assert len(result["cat"]) == 1
    # 高優先度 DB (reader_a) の翻訳が採用される (_merge_by_key と同じ後勝ち意味論)
    assert result["cat"][0]["translations"] == {"japanese": ["猫A"]}


def _seed_search_rows(session: Session, tag_ids: range) -> None:
    session.add(TagFormat(format_id=1, format_name="test"))
    session.add(TagTypeName(type_name_id=1, type_name="general"))
    session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
    for tag_id in tag_ids:
        tag_name = f"sample_{tag_id}"
        session.add(Tag(tag_id=tag_id, tag=tag_name, source_tag=tag_name))
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
