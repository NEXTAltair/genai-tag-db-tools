from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
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
    UserOverlayBase,
    UserTagStatusPatch,
)

pytestmark = pytest.mark.db_tools


def _memory_session_factory(*, overlay: bool = False) -> Callable[[], Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    if overlay:
        UserOverlayBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def session_factory() -> Callable[[], Session]:
    return _memory_session_factory()


def test_update_tags_type_batch_writes_base_tag_type_overlay_patch() -> None:
    """Base DB 由来タグの type 補正は USER_TAG_STATUS_PATCH に保存する (#1268/#136)。"""
    from genai_tag_db_tools.models import TagTypeUpdate

    base_factory = _memory_session_factory()
    user_factory = _memory_session_factory(overlay=True)
    base_reader = TagReader(base_factory)
    user_reader = OverlayTagReader(user_factory)
    merged_reader = MergedTagReader(base_repo=base_reader, user_repo=user_reader)
    repo = TagRepository(user_factory, reader=merged_reader)

    base_tag_id = 197273
    with base_factory() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=base_tag_id, tag="base_only_tag", source_tag="Base Only Tag"))
        session.add(TagStatus(tag_id=base_tag_id, format_id=1, type_id=0, alias=False, preferred_tag_id=base_tag_id))
        session.add(TagTranslation(tag_id=base_tag_id, language="ja", translation="ベースのみ"))
        session.commit()

    with user_factory() as session:
        session.add(TagFormat(format_id=1000, format_name="Lorairo"))
        session.commit()

    repo.update_tags_type_batch(
        [
            TagTypeUpdate(tag_id=base_tag_id, type_name="general"),
            TagTypeUpdate(tag_id=base_tag_id, type_name="general"),
        ],
        format_id=1000,
    )

    with user_factory() as session:
        assert session.query(Tag).filter(Tag.tag_id == base_tag_id).one_or_none() is None
        assert session.query(TagStatus).filter(TagStatus.tag_id == base_tag_id).one_or_none() is None
        patch = (
            session.query(UserTagStatusPatch)
            .filter(
                UserTagStatusPatch.target_scope == "base",
                UserTagStatusPatch.target_tag_id == base_tag_id,
                UserTagStatusPatch.format_id == 1000,
            )
            .one()
        )
        type_name = (
            session.query(TagTypeName.type_name)
            .join(TagTypeFormatMapping, TagTypeName.type_name_id == TagTypeFormatMapping.type_name_id)
            .filter(TagTypeFormatMapping.format_id == 1000, TagTypeFormatMapping.type_id == patch.type_id)
            .scalar()
        )

    assert patch.alias is False
    assert patch.preferred_scope == "base"
    assert patch.preferred_tag_id == base_tag_id
    assert type_name == "general"

    rows = merged_reader.search_tags("base_only_tag", format_name="Lorairo", type_name="general")

    assert len(rows) == 1
    assert rows[0]["tag_id"] == base_tag_id
    assert rows[0]["translations"] == {"ja": ["ベースのみ"]}
    assert "danbooru" in rows[0]["format_statuses"]
    assert "Lorairo" in rows[0]["format_statuses"]

    bulk_row = merged_reader.search_tags_bulk(["base_only_tag"], format_name="Lorairo")["base_only_tag"]
    bulk_all_row = merged_reader.search_tags_bulk_all(["base_only_tag"], format_name="Lorairo")[
        "base_only_tag"
    ][0]

    assert bulk_row["translations"] == {"ja": ["ベースのみ"]}
    assert "Lorairo" in bulk_row["format_statuses"]
    assert bulk_all_row["translations"] == {"ja": ["ベースのみ"]}
    assert "Lorairo" in bulk_all_row["format_statuses"]

    with base_factory() as session:
        session.add(Tag(tag_id=base_tag_id + 1, tag="unpatched_base", source_tag="Unpatched Base"))
        session.add(
            TagStatus(
                tag_id=base_tag_id + 1,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=base_tag_id + 1,
            )
        )
        session.commit()

    assert merged_reader.search_tags("unpatched_base", format_name="Lorairo") == []
    assert merged_reader.search_tags_bulk(["unpatched_base"], format_name="Lorairo") == {}
    assert merged_reader.search_tags_bulk_all(["unpatched_base"], format_name="Lorairo") == {}


def test_update_tags_type_batch_rolls_back_overlay_patch_when_batch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """後続更新が失敗したら、同一 batch 内の overlay patch も rollback する。"""
    from genai_tag_db_tools.models import TagTypeUpdate

    base_factory = _memory_session_factory()
    user_factory = _memory_session_factory(overlay=True)
    base_reader = TagReader(base_factory)
    user_reader = OverlayTagReader(user_factory)
    merged_reader = MergedTagReader(base_repo=base_reader, user_repo=user_reader)
    repo = TagRepository(user_factory, reader=merged_reader)

    base_tag_id = 197273
    with base_factory() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=base_tag_id, tag="base_only_tag", source_tag="Base Only Tag"))
        session.add(TagStatus(tag_id=base_tag_id, format_id=1, type_id=0, alias=False, preferred_tag_id=base_tag_id))
        session.commit()

    with user_factory() as session:
        session.add(TagFormat(format_id=1000, format_name="Lorairo"))
        session.commit()

    def _raise_on_legacy_path(*args: object, **kwargs: object) -> None:
        raise RuntimeError("legacy path failed")

    monkeypatch.setattr(repo, "_write_tag_status_in_session", _raise_on_legacy_path)

    with pytest.raises(RuntimeError, match="legacy path failed"):
        repo.update_tags_type_batch(
            [
                TagTypeUpdate(tag_id=base_tag_id, type_name="general"),
                TagTypeUpdate(tag_id=999999, type_name="general"),
            ],
            format_id=1000,
        )

    with user_factory() as session:
        assert session.query(UserTagStatusPatch).all() == []


def test_create_tag_returns_existing_id(session_factory: Callable[[], Session]) -> None:
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))
    first_id = repo.create_tag("witch", "witch")
    second_id = repo.create_tag("witch", "witch")
    assert first_id == second_id


def test_create_tag_returns_inserted_id_without_reader_readback(
    session_factory: Callable[[], Session],
) -> None:
    """#124: reader 読み戻しに依存せず、挿入した行の id を直接返す。

    実運用では writer と reader の間に正規化・可視性のドリフトが起こり得る。
    「reader が常に None を返す」最悪ケースでも create_tag は挿入 id を返し、
    TAG_ID_NOT_FOUND_AFTER_INSERT 相当の失敗を起こしてはならない。
    """

    class _BlindReader:
        """挿入済みタグを見つけられない (ドリフトした) reader のスタブ。"""

        def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
            return None

    repo = TagRepository(session_factory, reader=_BlindReader())

    tag_id = repo.create_tag("__lock_test__", "lock test")

    assert isinstance(tag_id, int)
    with session_factory() as session:
        row = session.query(Tag).filter(Tag.tag == "lock test").one()
        assert row.tag_id == tag_id
        assert row.source_tag == "__lock_test__"


def test_create_tag_returns_existing_id_when_reader_is_blind(
    session_factory: Callable[[], Session],
) -> None:
    """#124: reader が既存タグを見落としても、同一 session の存在確認で既存 id を返す。"""

    class _BlindReader:
        def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> int | None:
            return None

    repo = TagRepository(session_factory, reader=_BlindReader())
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


# ==============================================================================
# register_tag_with_status: parent(TAGS) + child(TAG_STATUS) の atomicity (#1239)
# ==============================================================================


def _seed_format_and_mapping(session_factory: Callable[[], Session]) -> None:
    """format_id=1 / type_id=0(unknown) の mapping を seed する。"""
    with session_factory() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.add(TagTypeName(type_name_id=0, type_name="unknown"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=0))
        session.commit()


def test_register_tag_with_status_writes_parent_and_child_atomically(
    session_factory: Callable[[], Session],
) -> None:
    """#1239: TAGS 行・TAG_STATUS 行・翻訳を単一トランザクションで束ねて書く。"""
    _seed_format_and_mapping(session_factory)
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))

    tag_id = repo.register_tag_with_status(
        source_tag="newtag",
        tag="newtag",
        existing_tag_id=None,
        format_id=1,
        type_id=0,
        alias=False,
        preferred_tag_id=None,
        translations=[("ja", "新タグ")],
    )

    with session_factory() as session:
        tag_row = session.query(Tag).filter(Tag.tag == "newtag").one()
        assert tag_row.tag_id == tag_id
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.alias is False
        # alias=False では preferred_tag_id は自身の id に一致する
        assert status.preferred_tag_id == tag_id
        assert status.type_id == 0
        translation = session.query(TagTranslation).filter(TagTranslation.tag_id == tag_id).one()
        assert translation.translation == "新タグ"


def test_register_tag_with_status_rolls_back_parent_when_status_fails(
    session_factory: Callable[[], Session],
) -> None:
    """#1239: child(TAG_STATUS) 書き込みが失敗したら parent(TAGS) も rollback される。

    非 atomic な旧実装では create_tag が単独 commit するため、後続の status 失敗時に
    TAGS 行だけが孤児として残っていた。atomic 化後は type_id マッピング不整合で
    status 書き込みが失敗すると、直前に flush した TAGS 行も一緒に rollback される。
    """
    _seed_format_and_mapping(session_factory)
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))

    # type_id=5 は mapping が無いため _validate_type_mapping が commit 前に ValueError を送出
    with pytest.raises(ValueError):
        repo.register_tag_with_status(
            source_tag="orphan",
            tag="orphan",
            existing_tag_id=None,
            format_id=1,
            type_id=5,
            alias=False,
            preferred_tag_id=None,
        )

    with session_factory() as session:
        # parent TAGS 行が孤児として残っていないこと
        assert session.query(Tag).filter(Tag.tag == "orphan").one_or_none() is None
        assert session.query(TagStatus).count() == 0


def test_register_tag_with_status_reuses_existing_tag_id(
    session_factory: Callable[[], Session],
) -> None:
    """#1239: existing_tag_id 指定時は新規 TAGS 行を作らず既存 id に status を張る。"""
    _seed_format_and_mapping(session_factory)
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))

    existing_id = repo.create_tag("existing", "existing")

    returned_id = repo.register_tag_with_status(
        source_tag="existing",
        tag="existing",
        existing_tag_id=existing_id,
        format_id=1,
        type_id=0,
        alias=False,
        preferred_tag_id=None,
    )

    assert returned_id == existing_id
    with session_factory() as session:
        # 重複 TAGS 行を作っていないこと
        assert session.query(Tag).filter(Tag.tag == "existing").count() == 1
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == existing_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.preferred_tag_id == existing_id


def test_register_tag_with_status_ignores_user_scope_existing_tag_id(
    session_factory: Callable[[], Session],
) -> None:
    """#1265: base TAGS に存在しない existing_tag_id (user scope 由来の 1e9+ id 等) を渡されても、
    その id を信頼せず tag 文字列で再解決/新規作成する。

    MergedTagReader は user scope 優先で解決するため、base 登録経路に user scope の tag_id が
    渡ることがある。その値を base TAGS 実在チェック無しに TAG_STATUS へ INSERT すると
    ``FOREIGN KEY constraint failed`` になっていた (#1265)。
    """
    _seed_format_and_mapping(session_factory)
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))

    user_scope_id = 1_000_009_635  # base TAGS には存在しない user scope の tag_id

    returned_id = repo.register_tag_with_status(
        source_tag="dataset_tag",
        tag="dataset_tag",
        existing_tag_id=user_scope_id,
        format_id=1,
        type_id=0,
        alias=False,
        preferred_tag_id=None,
    )

    # user scope id をそのまま使わず base に採番された新 id を返す
    assert returned_id != user_scope_id
    with session_factory() as session:
        tag_row = session.query(Tag).filter(Tag.tag == "dataset_tag").one()
        assert tag_row.tag_id == returned_id
        # status は base の新 tag_id で挿入され FK 違反にならない
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == returned_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.preferred_tag_id == returned_id
        # user scope id の孤児 status 行が残らないこと
        assert session.query(TagStatus).filter(TagStatus.tag_id == user_scope_id).count() == 0


def test_register_tag_with_status_reresolves_by_tag_when_existing_id_missing(
    session_factory: Callable[[], Session],
) -> None:
    """#1265: existing_tag_id が base TAGS に存在せず、同名 tag が既に base TAGS にある場合は
    その既存 base 行を再利用し、重複 TAGS 行を作らない。"""
    _seed_format_and_mapping(session_factory)
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))

    base_id = repo.create_tag("shared", "shared")
    bogus_id = 1_000_042_000  # base TAGS に存在しない (user scope 由来を模した値)

    returned_id = repo.register_tag_with_status(
        source_tag="shared",
        tag="shared",
        existing_tag_id=bogus_id,
        format_id=1,
        type_id=0,
        alias=False,
        preferred_tag_id=None,
    )

    assert returned_id == base_id
    with session_factory() as session:
        # 重複 TAGS 行を作らず既存 base 行を再利用する
        assert session.query(Tag).filter(Tag.tag == "shared").count() == 1
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == base_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.preferred_tag_id == base_id


def test_register_tag_with_status_type_id_none_defaults_and_preserves(
    session_factory: Callable[[], Session],
) -> None:
    """#1249: type_id=None は新規 status では 0、既存 status では現在値を保持する。

    update_deprecated_tags / GUI fallback は type_id を渡さない従来挙動を持つため、
    register_tag_with_status が type_id=None を「既存値保持 / 新規は 0」として扱えることを
    保証する。
    """
    _seed_format_and_mapping(session_factory)
    # 非 0 の type mapping (format_id=1, type_id=2) も seed する
    with session_factory() as session:
        session.add(TagTypeName(type_name_id=2, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=2, type_name_id=2))
        session.commit()
    reader = TagReader(session_factory)
    repo = TagRepository(session_factory, reader=MergedTagReader(base_repo=reader))

    # 新規 status: type_id=None -> 0
    new_id = repo.register_tag_with_status(
        source_tag="newdep",
        tag="newdep",
        existing_tag_id=None,
        format_id=1,
        type_id=None,
        alias=False,
        preferred_tag_id=None,
    )
    with session_factory() as session:
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == new_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.type_id == 0

    # 既存 status を type_id=2 で作り直してから type_id=None で更新 -> 2 を保持
    repo.update_tag_status(tag_id=new_id, format_id=1, alias=False, preferred_tag_id=new_id, type_id=2)
    repo.register_tag_with_status(
        source_tag="newdep",
        tag="newdep",
        existing_tag_id=new_id,
        format_id=1,
        type_id=None,
        alias=False,
        preferred_tag_id=None,
    )
    with session_factory() as session:
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == new_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.type_id == 2
