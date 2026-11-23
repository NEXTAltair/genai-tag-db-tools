"""Broad searches must split SQL statements before SQLite's bind variable limit."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from sqlalchemy import StaticPool, create_engine, insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.query_utils import TAG_ID_IN_CHUNK
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
    UserTagTranslationPatch,
    UserTagTranslationTombstone,
    UserTagTypePatch,
    UserTagUsagePatch,
)

pytestmark = pytest.mark.db_tools

# Two complete chunks and a tail: exercise the actual production chunk size.
_COUNT = 2 * TAG_ID_IN_CHUNK + 7
_VARIABLE_LIMIT = 999


def _create_overlay_engine() -> Engine:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.add(TagTypeName(type_name_id=1, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=1, type_name_id=1))
        session.commit()
    return engine


@pytest.fixture
def overlay_engine() -> Iterator[Engine]:
    engine = _create_overlay_engine()
    yield engine
    engine.dispose()


def _limit_variables(engine: Engine) -> None:
    # Modern SQLite often accepts 32,766+ variables; a real connection limit
    # reproduces the failure without a huge database or mocked SQL execution.
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert isinstance(raw, sqlite3.Connection)
        raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _VARIABLE_LIMIT)
        assert raw.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) == _VARIABLE_LIMIT


def _seed_patches(engine: Engine, *, scope: str, offset: int) -> None:
    # 準備データは executemany で一括投入する (内容は 1 件ずつ add していた時と同一)。
    other_scope = "base" if scope == "user" else "user"
    indexes = range(1, _COUNT + 1)
    with Session(engine) as session:
        session.execute(
            insert(UserTagStatusPatch),
            [
                {
                    "target_scope": scope,
                    "target_tag_id": offset + index,
                    "format_id": 1,
                    "type_id": 0,
                    "alias": index % 3 == 0,
                    "preferred_scope": scope,
                    "preferred_tag_id": offset + 1 if index % 3 == 0 else offset + index,
                    "deprecated": index % 5 == 0,
                }
                for index in indexes
            ],
        )
        session.execute(
            insert(UserTagTypePatch),
            [
                {"target_scope": scope, "target_tag_id": offset + index, "format_id": 1, "type_id": 1}
                for index in indexes
            ],
        )
        session.execute(
            insert(UserTagUsagePatch),
            [
                {"target_scope": scope, "target_tag_id": offset + index, "format_id": 1, "count": index}
                for index in indexes
            ],
        )
        session.execute(
            insert(UserTagTranslationPatch),
            [
                {"target_scope": scope, "target_tag_id": offset + index, "language": "ja", "translation": t}
                for index in indexes
                for t in (f"訳{index}", f"別訳{index}", f"hidden{index}")
            ],
        )
        session.execute(
            insert(UserTagTranslationTombstone),
            [
                {
                    "target_scope": scope,
                    "target_tag_id": offset + index,
                    "language": "ja",
                    "translation": f"hidden{index}",
                }
                for index in indexes
            ]
            # A tombstone in the other scope must not hide this visible patch.
            + [
                {
                    "target_scope": other_scope,
                    "target_tag_id": offset + index,
                    "language": "ja",
                    "translation": f"訳{index}",
                }
                for index in indexes
            ],
        )
        session.commit()


@pytest.fixture(scope="module")
def overlay() -> Iterator[OverlayTagReader]:
    # module scope で 1 回だけ作る。この fixture を使うテストは検索だけで DB を書き換えない
    # (書き換えるテストは function scope の overlay_engine を使うこと)。
    engine = _create_overlay_engine()
    with Session(engine) as session:
        session.add_all(
            UserTag(tag_id=USER_TAG_ID_OFFSET + i, tag=f"fa_{i}", source_tag=f"source_{i}")
            for i in range(1, _COUNT + 1)
        )
        session.commit()
    _seed_patches(engine, scope="user", offset=USER_TAG_ID_OFFSET)
    _limit_variables(engine)
    yield OverlayTagReader(sessionmaker(bind=engine, autoflush=False))
    engine.dispose()


@pytest.mark.parametrize("keyword", ["fa", "source", "訳"])
def test_overlay_search_keeps_all_candidates_and_patch_values(
    overlay: OverlayTagReader, keyword: str
) -> None:
    rows = overlay.search_tags(keyword, partial=True, format_name="danbooru")

    assert [row["tag_id"] for row in rows] == [USER_TAG_ID_OFFSET + i for i in range(1, _COUNT + 1)]
    for index, row in enumerate(rows, start=1):
        assert row["type_id"] == 1  # Type patch overrides the status patch's type 0.
        assert row["type_name"] == "character"
        assert row["usage_count"] == index
        assert row["alias"] is (index % 3 == 0)
        assert row["deprecated"] is (index % 5 == 0)
        assert set(row["translations"]["ja"]) == {f"訳{index}", f"別訳{index}"}

    # Filtering and pagination happen over the complete candidate set, including
    # matches beyond both chunk boundaries, rather than an early truncated page.
    filtered = overlay.search_tags(
        keyword,
        partial=True,
        format_name="danbooru",
        type_name="character",
        language="ja",
        alias=False,
        deprecated=False,
        min_usage=_COUNT - 20,
        max_usage=_COUNT,
        offset=1,
        limit=3,
    )
    expected = [i for i in range(_COUNT - 20, _COUNT + 1) if i % 3 and i % 5][1:4]
    assert [row["tag_id"] for row in filtered] == [USER_TAG_ID_OFFSET + i for i in expected]


def test_translation_batch_deduplicates_ids_across_chunks(overlay: OverlayTagReader) -> None:
    ids = [USER_TAG_ID_OFFSET + i for i in range(1, _COUNT + 1)]
    translations = overlay.get_translations_batch(
        ids + list(reversed(ids)) + [USER_TAG_ID_OFFSET + _COUNT + 1]
    )

    assert set(translations) == set(ids)
    for index, tag_id in enumerate(ids, start=1):
        values = translations[tag_id]
        assert len(values) == 2
        assert {value.translation for value in values} == {f"訳{index}", f"別訳{index}"}
    for tag_id in (ids[0], ids[TAG_ID_IN_CHUNK], ids[-1]):
        assert [value.translation for value in translations[tag_id]] == [
            value.translation for value in overlay.get_translations(tag_id)
        ]


def test_merged_search_with_small_page_keeps_base_and_overlay_translations(overlay_engine: Engine) -> None:
    base_engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(base_engine)
    try:
        with Session(base_engine) as session:
            indexes = range(1, _COUNT + 1)
            session.execute(
                insert(Tag), [{"tag_id": i, "tag": f"fa_{i}", "source_tag": f"fa_{i}"} for i in indexes]
            )
            session.execute(
                insert(TagTranslation),
                [
                    {"tag_id": i, "language": "ja", "translation": t}
                    for i in indexes
                    for t in (f"訳{i}", f"基底{i}", f"hidden{i}")
                ],
            )
            session.commit()
        _seed_patches(overlay_engine, scope="base", offset=0)
        _limit_variables(base_engine)
        _limit_variables(overlay_engine)
        merged = MergedTagReader(
            base_repo=TagReader(sessionmaker(bind=base_engine, autoflush=False)),
            user_repo=OverlayTagReader(sessionmaker(bind=overlay_engine, autoflush=False)),
        )

        # Reproduce the suggestion path: a short partial keyword and a small
        # requested page still apply overlays to every matching base tag.
        rows = merged.search_tags("fa", partial=True, limit=20, offset=_COUNT - 20)

        assert [row["tag_id"] for row in rows] == list(range(_COUNT - 19, _COUNT + 1))
        for row in rows:
            index = row["tag_id"]
            assert row["type_id"] == 1
            assert row["alias"] is (index % 3 == 0)
            assert row["deprecated"] is (index % 5 == 0)
            assert row["format_statuses"]["danbooru"]["usage_count"] == index
            translations = row["translations"]["ja"]
            assert len(translations) == 3
            assert set(translations) == {f"訳{index}", f"基底{index}", f"別訳{index}"}
    finally:
        base_engine.dispose()
