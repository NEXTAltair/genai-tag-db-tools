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


def test_initial_tag_ids_exact_match_is_case_insensitive(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="blue_hair", tag="blue hair"))
        session.commit()
        builder = TagSearchQueryBuilder(session)
        ids = builder.initial_tag_ids("Blue Hair", use_like=False)

    assert ids == {1}


def test_initial_tag_ids_for_keywords_is_case_insensitive(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="blue_hair", tag="blue hair"))
        session.commit()
        builder = TagSearchQueryBuilder(session)
        result = builder.initial_tag_ids_for_keywords(["Blue Hair"])

    assert result == {"Blue Hair": {1}}


def test_filtered_tag_ids_applies_filters_before_limit(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=6)
        session.add(TagTypeName(type_name_id=2, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=1, type_name_id=2))
        for tag_id in range(1, 4):
            status = session.get(TagStatus, (tag_id, 1))
            assert status is not None
            status.type_id = 1
            session.add(TagUsageCounts(tag_id=tag_id, format_id=1, count=1))
        for tag_id in range(4, 7):
            session.add(TagUsageCounts(tag_id=tag_id, format_id=1, count=100))
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, format_id = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            format_names=["test"],
            type_names=["general"],
            min_usage=10,
            limit=2,
        )

    assert sorted(ids) == [4, 5]
    assert format_id == 1


def test_filtered_tag_ids_filters_alias_and_deprecated_before_limit(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=5)
        first = session.get(TagStatus, (1, 1))
        second = session.get(TagStatus, (2, 1))
        assert first is not None
        assert second is not None
        first.alias = True
        first.preferred_tag_id = 2
        second.deprecated = True
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, _ = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            format_names=["test"],
            alias=False,
            deprecated=False,
            limit=2,
        )

    assert sorted(ids) == [3, 4]


def test_filtered_tag_ids_treats_all_as_unfiltered(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=4)
        builder = TagSearchQueryBuilder(session)
        ids, format_id = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            format_names=["all"],
            type_names=["all"],
            limit=2,
        )

    assert sorted(ids) == [1, 2]
    assert format_id == 0


def test_filtered_tag_ids_negative_status_filters_keep_statusless_tags(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="sample_statusless", tag="sample_statusless"))
        session.add(TagFormat(format_id=1, format_name="test"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=2, source_tag="sample_active", tag="sample_active"))
        session.add(
            TagStatus(
                tag_id=2,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=2,
                deprecated=False,
            )
        )
        session.add(Tag(tag_id=3, source_tag="sample_deprecated", tag="sample_deprecated"))
        session.add(
            TagStatus(
                tag_id=3,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=3,
                deprecated=True,
            )
        )
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, _ = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            alias=False,
            deprecated=False,
        )

    assert sorted(ids) == [1, 2]


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
