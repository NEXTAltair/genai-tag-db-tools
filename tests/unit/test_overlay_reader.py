"""OverlayTagReader の単体テスト。"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    TagFormat,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
)
from genai_tag_db_tools.models import TagSearchRow


@pytest.fixture
def overlay_engine(tmp_path: Path):
    """UserOverlayBase + Base の両テーブルを持つインメモリ SQLite エンジン。"""
    db_path = tmp_path / "test_overlay.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def overlay_session_factory(overlay_engine):
    """テスト用セッションファクトリ。"""
    return sessionmaker(bind=overlay_engine, autoflush=False, autocommit=False)


@pytest.fixture
def overlay_reader(overlay_session_factory):
    """テスト対象の OverlayTagReader インスタンス。"""
    return OverlayTagReader(session_factory=overlay_session_factory)


class TestOverlayTagReaderGetTag:
    """get_tag_by_id / get_tag_id_by_name の基本動作を検証する。"""

    def test_get_tag_by_id_found(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 1
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="my_src", tag="my_tag"))
            session.commit()

        tag = overlay_reader.get_tag_by_id(tag_id)
        assert tag is not None
        assert tag.tag_id == tag_id
        assert tag.tag == "my_tag"
        assert tag.source_tag == "my_src"

    def test_get_tag_by_id_not_found(self, overlay_reader):
        assert overlay_reader.get_tag_by_id(USER_TAG_ID_OFFSET + 999) is None

    def test_get_tag_id_by_name_exact(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 2
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="exact_src", tag="exact_tag"))
            session.commit()

        result = overlay_reader.get_tag_id_by_name("exact_tag")
        assert result == tag_id

    def test_get_tag_id_by_name_not_found(self, overlay_reader):
        assert overlay_reader.get_tag_id_by_name("nonexistent") is None

    def test_get_tag_id_by_name_partial(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 3
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="partial_src", tag="partial_match_tag"))
            session.commit()

        result = overlay_reader.get_tag_id_by_name("partial", partial=True)
        assert result == tag_id

    def test_list_tags(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 10, source_tag="s1", tag="list_tag1"))
            session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 11, source_tag="s2", tag="list_tag2"))
            session.commit()

        tags = overlay_reader.list_tags()
        assert len(tags) == 2
        tag_ids = {t.tag_id for t in tags}
        assert USER_TAG_ID_OFFSET + 10 in tag_ids
        assert USER_TAG_ID_OFFSET + 11 in tag_ids

    def test_get_all_tag_ids(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 20, source_tag="s1", tag="all_ids1"))
            session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 21, source_tag="s2", tag="all_ids2"))
            session.commit()

        ids = overlay_reader.get_all_tag_ids()
        assert USER_TAG_ID_OFFSET + 20 in ids
        assert USER_TAG_ID_OFFSET + 21 in ids

    def test_get_max_tag_id(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 100, source_tag="s", tag="max_tag"))
            session.commit()

        assert overlay_reader.get_max_tag_id() >= USER_TAG_ID_OFFSET + 100

    def test_search_tag_ids(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 30
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="srch_src", tag="search_ids_tag"))
            session.commit()

        ids = overlay_reader.search_tag_ids("search_ids_tag")
        assert tag_id in ids

    def test_search_tag_ids_partial(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 31
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="ps", tag="partial_ids_tag"))
            session.commit()

        ids = overlay_reader.search_tag_ids("partial_ids", partial=True)
        assert tag_id in ids


class TestOverlayTagReaderStatus:
    """get_tag_status / list_tag_statuses の基本動作を検証する。"""

    def _make_patch(
        self,
        tag_id: int,
        format_id: int,
        *,
        alias: bool = False,
        deprecated: bool = False,
    ) -> UserTagStatusPatch:
        return UserTagStatusPatch(
            target_scope="user",
            target_tag_id=tag_id,
            format_id=format_id,
            type_id=0,
            alias=alias,
            preferred_scope="user",
            preferred_tag_id=tag_id,
            deprecated=deprecated,
        )

    def test_get_tag_status_found(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 200
        format_id = 1000
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="st_src", tag="status_tag"))
            session.add(self._make_patch(tag_id, format_id))
            session.commit()

        status = overlay_reader.get_tag_status(tag_id, format_id)
        assert status is not None
        assert status.tag_id == tag_id
        assert status.format_id == format_id
        assert status.alias is False
        assert status.deprecated is False

    def test_get_tag_status_not_found(self, overlay_reader):
        assert overlay_reader.get_tag_status(USER_TAG_ID_OFFSET + 999, 1000) is None

    def test_list_tag_statuses_all(self, overlay_reader, overlay_session_factory):
        tag_id1 = USER_TAG_ID_OFFSET + 210
        tag_id2 = USER_TAG_ID_OFFSET + 211
        format_id = 1000
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id1, source_tag="s1", tag="lst_stat1"))
            session.add(UserTag(tag_id=tag_id2, source_tag="s2", tag="lst_stat2"))
            session.add(self._make_patch(tag_id1, format_id))
            session.add(self._make_patch(tag_id2, format_id, deprecated=True))
            session.commit()

        statuses = overlay_reader.list_tag_statuses()
        assert len(statuses) == 2
        deprecated_flags = {s.tag_id: s.deprecated for s in statuses}
        assert deprecated_flags[tag_id2] is True

    def test_list_tag_statuses_filtered(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 220
        format_id = 1000
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="fs", tag="filtered_stat_tag"))
            session.add(self._make_patch(tag_id, format_id))
            session.commit()

        statuses = overlay_reader.list_tag_statuses(tag_id=tag_id)
        assert len(statuses) == 1
        assert statuses[0].tag_id == tag_id

    def test_list_tag_statuses_returns_empty_for_unknown(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 230
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="ns", tag="no_status_tag"))
            session.commit()

        statuses = overlay_reader.list_tag_statuses(tag_id=tag_id)
        assert statuses == []


class TestOverlayTagReaderSearch:
    """search_tags のキーワードヒット動作を検証する。"""

    class _BaseSearchReader:
        def search_tags(self, keyword: str, **kwargs) -> list[TagSearchRow]:
            if keyword != "blue eyes":
                return []
            return [
                {
                    "tag_id": 20,
                    "tag": "blue eyes",
                    "source_tag": "blue_eyes",
                    "usage_count": 10,
                    "alias": False,
                    "deprecated": False,
                    "type_id": 0,
                    "type_name": "general",
                    "translations": {},
                    "format_statuses": {"1": {"alias": False, "deprecated": False, "type_id": 0}},
                }
            ]

    def test_search_tags_exact_match(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 300
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="srch_src", tag="search_exact"))
            session.commit()

        rows = overlay_reader.search_tags("search_exact")
        assert len(rows) == 1
        assert rows[0]["tag_id"] == tag_id
        assert rows[0]["tag"] == "search_exact"
        assert rows[0]["source_tag"] == "srch_src"

    def test_search_tags_partial_match(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 310
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="ps", tag="partial_keyword_result"))
            session.commit()

        rows = overlay_reader.search_tags("keyword", partial=True)
        assert len(rows) == 1
        assert rows[0]["tag_id"] == tag_id

    def test_search_tags_not_found(self, overlay_reader):
        assert overlay_reader.search_tags("no_such_tag") == []

    def test_search_tags_with_status(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 320
        format_id = 1000
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="ws_src", tag="with_status_tag"))
            session.add(
                UserTagStatusPatch(
                    target_scope="user",
                    target_tag_id=tag_id,
                    format_id=format_id,
                    type_id=0,
                    alias=False,
                    preferred_scope="user",
                    preferred_tag_id=tag_id,
                    deprecated=True,
                )
            )
            session.commit()

        rows = overlay_reader.search_tags("with_status_tag")
        assert len(rows) == 1
        row = rows[0]
        assert row["deprecated"] is True
        assert row["alias"] is False
        assert str(format_id) in row["format_statuses"]

    def test_search_tags_row_fields(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 330
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="rf_src", tag="row_fields_tag"))
            session.commit()

        rows = overlay_reader.search_tags("row_fields_tag")
        assert len(rows) == 1
        row = rows[0]
        assert row["usage_count"] == 0
        assert row["type_name"] == ""
        assert row["translations"] == {}
        assert row["format_statuses"] == {}

    def test_merged_search_applies_base_scope_status_patch(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(
                UserTagStatusPatch(
                    target_scope="base",
                    target_tag_id=20,
                    format_id=1,
                    type_id=5,
                    alias=True,
                    preferred_scope="base",
                    preferred_tag_id=99,
                    deprecated=True,
                )
            )
            session.commit()

        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        rows = merged.search_tags("blue eyes")

        assert len(rows) == 1
        assert rows[0]["alias"] is True
        assert rows[0]["deprecated"] is True
        assert rows[0]["type_id"] == 5
        assert rows[0]["format_statuses"]["1"]["deprecated"] is True


class TestOverlayTagReaderMetadata:
    def test_get_tag_formats_returns_user_formats(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(TagFormat(format_id=3001, format_name="lorairo"))
            session.commit()

        assert overlay_reader.get_tag_format_ids() == [3001]
        assert overlay_reader.get_tag_formats() == ["lorairo"]
        assert overlay_reader.get_format_map() == {3001: "lorairo"}

    def test_type_mapping_methods_read_user_db_mappings(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(TagFormat(format_id=3001, format_name="lorairo"))
            session.add(TagTypeName(type_name_id=9001, type_name="general"))
            session.add(TagTypeName(type_name_id=9002, type_name="meta"))
            session.add(TagTypeFormatMapping(format_id=3001, type_id=0, type_name_id=9001))
            session.add(TagTypeFormatMapping(format_id=3001, type_id=5, type_name_id=9002))
            session.commit()

        assert overlay_reader.get_type_mapping_map() == {
            (3001, 0): "general",
            (3001, 5): "meta",
        }
        assert overlay_reader.get_type_name_by_format_type_id(3001, 0) == "general"
        assert overlay_reader.get_type_name_id("meta") == 9002
        assert overlay_reader.get_type_id_for_format("meta", 3001) == 5


class TestOverlayTagReaderEmpty:
    """空 DB で各メソッドが安全にデフォルト値を返すことを検証する。"""

    def test_get_tag_by_id_empty_db(self, overlay_reader):
        assert overlay_reader.get_tag_by_id(USER_TAG_ID_OFFSET + 1) is None

    def test_get_tag_id_by_name_empty_db(self, overlay_reader):
        assert overlay_reader.get_tag_id_by_name("anything") is None

    def test_list_tags_empty_db(self, overlay_reader):
        assert overlay_reader.list_tags() == []

    def test_get_all_tag_ids_empty_db(self, overlay_reader):
        assert overlay_reader.get_all_tag_ids() == []

    def test_get_max_tag_id_empty_db(self, overlay_reader):
        assert overlay_reader.get_max_tag_id() == 0

    def test_search_tag_ids_empty_db(self, overlay_reader):
        assert overlay_reader.search_tag_ids("anything") == []

    def test_get_tag_status_empty_db(self, overlay_reader):
        assert overlay_reader.get_tag_status(USER_TAG_ID_OFFSET + 1, 1000) is None

    def test_list_tag_statuses_empty_db(self, overlay_reader):
        assert overlay_reader.list_tag_statuses() == []

    def test_search_tags_empty_db(self, overlay_reader):
        assert overlay_reader.search_tags("anything") == []

    def test_stub_methods_return_defaults(self, overlay_reader):
        assert overlay_reader.get_translations(USER_TAG_ID_OFFSET + 1) == []
        assert overlay_reader.list_translations() == []
        assert overlay_reader.get_translations_batch([]) == {}
        assert overlay_reader.get_format_name(1000) is None
        assert overlay_reader.get_format_id("any") == 0
        assert overlay_reader.get_format_map() == {}
        assert overlay_reader.get_tag_format_ids() == []
        assert overlay_reader.get_tag_formats() == []
        assert overlay_reader.get_tag_languages() == []
        assert overlay_reader.get_type_mapping_map() == {}
        assert overlay_reader.get_type_name_by_format_type_id(1000, 0) is None
        assert overlay_reader.get_type_name_id("unknown") is None
        assert overlay_reader.get_type_id_for_format("unknown", 1000) is None
        assert overlay_reader.get_usage_count(USER_TAG_ID_OFFSET + 1, 1000) is None
        assert overlay_reader.list_usage_counts() == []
        assert overlay_reader.get_tag_types(1000) == []
        assert overlay_reader.get_all_types() == []
        assert overlay_reader.get_unknown_type_tag_ids(1000) == []
        assert overlay_reader.get_metadata_value("version") is None
        assert overlay_reader.search_tags_bulk(["tag"]) == {}
