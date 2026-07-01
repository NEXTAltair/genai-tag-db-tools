"""OverlayTagReader の単体テスト。"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
    UserTagTranslationPatch,
    UserTagUsagePatch,
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
        _rows: ClassVar[dict[int, TagSearchRow]] = {
            20: {
                "tag_id": 20,
                "tag": "blue eyes",
                "source_tag": "blue_eyes",
                "usage_count": 10,
                "alias": False,
                "deprecated": False,
                "type_id": 1,
                "type_name": "general",
                "translations": {},
                "format_statuses": {
                    "danbooru": {
                        "alias": False,
                        "deprecated": False,
                        "usage_count": 10,
                        "type_id": 1,
                        "type_name": "general",
                        "preferred_tag_id": 20,
                    }
                },
            },
            99: {
                "tag_id": 99,
                "tag": "azure eyes",
                "source_tag": "azure_eyes",
                "usage_count": 10,
                "alias": False,
                "deprecated": False,
                "type_id": 1,
                "type_name": "general",
                "translations": {},
                "format_statuses": {},
            },
        }

        def search_tags(self, keyword: str, **kwargs) -> list[TagSearchRow]:
            if keyword != "blue eyes":
                return []
            return [dict(self._rows[20])]  # type: ignore[list-item]

        def search_tags_bulk(self, keywords: list[str], **kwargs) -> dict[str, TagSearchRow]:
            return {keyword: dict(self._rows[20]) for keyword in keywords if keyword == "blue eyes"}  # type: ignore[misc]

        def search_tags_bulk_all(self, keywords: list[str], **kwargs) -> dict[str, list[TagSearchRow]]:
            return {
                keyword: [dict(self._rows[20])]  # type: ignore[list-item]
                for keyword in keywords
                if keyword == "blue eyes"
            }

        def get_tag_by_id(self, tag_id: int) -> Tag | None:
            row = self._rows.get(tag_id)
            if row is None:
                return None
            return Tag(tag_id=row["tag_id"], tag=row["tag"], source_tag=row["source_tag"])

        def list_tag_statuses(self, tag_id: int | None = None):
            return []

        def get_format_name(self, format_id: int) -> str | None:
            return {1: "danbooru", 2: "other"}.get(format_id)

        def get_format_map(self) -> dict[int, str]:
            return {1: "danbooru", 2: "other"}

        def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
            return {(1, 1): "general", (1, 4): "character", (2, 5): "style"}.get((format_id, type_id))

        def get_translations(self, tag_id: int):
            return []

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
        assert rows[0]["format_statuses"]["danbooru"]["deprecated"] is True

    def test_merged_search_filters_after_base_scope_status_patch(
        self, overlay_reader, overlay_session_factory
    ):
        with overlay_session_factory() as session:
            session.add(
                UserTagStatusPatch(
                    target_scope="base",
                    target_tag_id=20,
                    format_id=1,
                    type_id=4,
                    alias=False,
                    preferred_scope="base",
                    preferred_tag_id=20,
                    deprecated=True,
                )
            )
            session.commit()

        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        assert merged.search_tags("blue eyes", format_name="danbooru", deprecated=False) == []
        rows = merged.search_tags(
            "blue eyes", format_name="danbooru", deprecated=True, type_name="character"
        )
        assert len(rows) == 1
        assert rows[0]["type_id"] == 4
        assert rows[0]["type_name"] == "character"

    def test_merged_search_applies_base_scope_usage_patch_to_filters(
        self, overlay_reader, overlay_session_factory
    ):
        with overlay_session_factory() as session:
            session.add(
                UserTagStatusPatch(
                    target_scope="base",
                    target_tag_id=20,
                    format_id=1,
                    type_id=1,
                    alias=False,
                    preferred_scope="base",
                    preferred_tag_id=20,
                    deprecated=False,
                )
            )
            session.add(TagUsageCounts(tag_id=20, format_id=1, count=10))
            session.commit()
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        user_repo = UserTagRepository(overlay_session_factory)
        user_repo.write_usage_patch("base", 20, 1, 123)
        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        rows = merged.search_tags("blue eyes", format_name="danbooru", min_usage=100)

        assert len(rows) == 1
        assert rows[0]["usage_count"] == 123
        assert rows[0]["format_statuses"]["danbooru"]["usage_count"] == 123

    def test_merged_search_finds_base_scope_translation_patch(
        self, overlay_reader, overlay_session_factory
    ):
        from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

        user_repo = UserTagRepository(overlay_session_factory)
        user_repo.write_translation_patch("base", 20, "ja", "青い目")
        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        rows = merged.search_tags("青い目", language="ja")

        assert len(rows) == 1
        assert rows[0]["tag_id"] == 20
        assert rows[0]["translations"] == {"ja": ["青い目"]}

    def test_merged_bulk_applies_base_scope_status_patch(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            session.add(
                UserTagStatusPatch(
                    target_scope="base",
                    target_tag_id=20,
                    format_id=1,
                    type_id=1,
                    alias=True,
                    preferred_scope="base",
                    preferred_tag_id=99,
                    deprecated=False,
                )
            )
            session.commit()

        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        result = merged.search_tags_bulk(["blue eyes"], format_name="danbooru", resolve_preferred=True)

        assert result["blue eyes"]["tag_id"] == 99
        assert result["blue eyes"]["tag"] == "azure eyes"

    def test_merged_bulk_all_applies_base_scope_status_patch(self, overlay_reader, overlay_session_factory):
        """search_tags_bulk_all も base-scope status patch + cross-scope preferred を解決する (#998)。"""
        with overlay_session_factory() as session:
            session.add(
                UserTagStatusPatch(
                    target_scope="base",
                    target_tag_id=20,
                    format_id=1,
                    type_id=1,
                    alias=True,
                    preferred_scope="base",
                    preferred_tag_id=99,
                    deprecated=False,
                )
            )
            session.commit()

        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        result = merged.search_tags_bulk_all(["blue eyes"], format_name="danbooru", resolve_preferred=True)

        assert [row["tag_id"] for row in result["blue eyes"]] == [99]
        assert result["blue eyes"][0]["tag"] == "azure eyes"

    def test_overlay_reader_search_tags_bulk_all_empty_when_no_match(self, overlay_reader):
        """OverlayTagReader.search_tags_bulk_all は未一致 keyword で空 dict を返す (#998)。"""
        assert overlay_reader.search_tags_bulk_all(["blue eyes"]) == {}

    def test_overlay_reader_search_tags_bulk_all_returns_user_rows(
        self, overlay_reader, overlay_session_factory
    ):
        """OverlayTagReader.search_tags_bulk_all は user タグの全マッチ行を返す (#998)。"""
        tag_id = USER_TAG_ID_OFFSET + 410
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="ub_src", tag="user_bulk_tag"))
            session.commit()

        result = overlay_reader.search_tags_bulk_all(["user_bulk_tag", "missing"])

        assert [row["tag_id"] for row in result["user_bulk_tag"]] == [tag_id]
        assert "missing" not in result

    def test_merged_bulk_all_merges_user_only_tag(self, overlay_reader, overlay_session_factory):
        """base bulk が拾えない user-only タグを user overlay の merge で取りこぼさない。

        MergedTagReader.search_tags_bulk_all は `_merge_search_tags_adaptive` (= search_tags)
        と同じく user_repo も merge するため、user-only タグを返す (#998, Codex PR #115 P2)。
        """
        tag_id = USER_TAG_ID_OFFSET + 400
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="uo_src", tag="user_only_tag"))
            session.commit()

        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        result = merged.search_tags_bulk_all(["user_only_tag"])

        assert [row["tag_id"] for row in result["user_only_tag"]] == [tag_id]

    def test_merged_bulk_all_user_only_reader_returns_user_tags(
        self, overlay_reader, overlay_session_factory
    ):
        """user-only reader (get_user_tag_reader 相当: Overlay を base とする) でも user 行を返す。

        get_user_tag_reader() は MergedTagReader(base_repo=OverlayTagReader, user_repo=None) を
        返す。base loop が Overlay の search_tags_bulk_all を叩くため user タグを取得できる
        (#998, Codex PR #115 P2)。
        """
        tag_id = USER_TAG_ID_OFFSET + 420
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="uor_src", tag="user_only_reader_tag"))
            session.commit()

        merged = MergedTagReader(base_repo=overlay_reader, user_repo=None)

        result = merged.search_tags_bulk_all(["user_only_reader_tag"])

        assert [row["tag_id"] for row in result["user_only_reader_tag"]] == [tag_id]

    def test_merged_bulk_all_returns_both_base_and_user_rows_for_same_keyword(
        self, overlay_reader, overlay_session_factory
    ):
        """同一 keyword が base タグと別 tag_id の user タグに一致したら両方返す。

        base hit があっても user overlay の別 tag_id 行を取りこぼさない (Codex PR #115 P2 の
        「additional user tag sharing a base keyword」ケース、#998)。
        """
        user_tag_id = USER_TAG_ID_OFFSET + 430
        with overlay_session_factory() as session:
            # base の "blue eyes" (tag_id 20) と同じ文字列を user タグとしても登録
            session.add(UserTag(tag_id=user_tag_id, source_tag="blue eyes", tag="blue eyes"))
            session.commit()

        merged = MergedTagReader(base_repo=self._BaseSearchReader(), user_repo=overlay_reader)

        result = merged.search_tags_bulk_all(["blue eyes"])

        assert {row["tag_id"] for row in result["blue eyes"]} == {20, user_tag_id}


class TestOverlayTagReaderSearchFilters:
    """search_tags の filter / 翻訳 / source_tag / usage 実装を検証する (#82/#83/#84)。"""

    def _make_status(
        self,
        tag_id: int,
        format_id: int,
        *,
        type_id: int = 0,
        alias: bool = False,
        deprecated: bool = False,
    ) -> UserTagStatusPatch:
        # CHECK 制約: alias=True のときは preferred を target と別にする必要がある。
        preferred_tag_id = tag_id if not alias else tag_id + 1
        return UserTagStatusPatch(
            target_scope="user",
            target_tag_id=tag_id,
            format_id=format_id,
            type_id=type_id,
            alias=alias,
            preferred_scope="user",
            preferred_tag_id=preferred_tag_id,
            deprecated=deprecated,
        )

    # --- #83: source_tag / 翻訳 / case-insensitive 検索 ---

    def test_search_matches_source_tag(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 400
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="raw_source", tag="normalized tag"))
            session.commit()

        rows = overlay_reader.search_tags("raw_source")
        assert len(rows) == 1
        assert rows[0]["tag_id"] == tag_id

    def test_search_exact_is_case_insensitive(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 401
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="MixedCaseSrc", tag="MixedCase"))
            session.commit()

        assert overlay_reader.search_tags("mixedcase")[0]["tag_id"] == tag_id
        assert overlay_reader.search_tags("MIXEDCASESRC")[0]["tag_id"] == tag_id

    def test_search_matches_translation_text(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 402
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="cat_src", tag="cat"))
            session.add(
                UserTagTranslationPatch(
                    target_scope="user", target_tag_id=tag_id, language="ja", translation="猫"
                )
            )
            session.commit()

        rows = overlay_reader.search_tags("猫")
        assert len(rows) == 1
        assert rows[0]["tag_id"] == tag_id
        assert rows[0]["translations"] == {"ja": ["猫"]}

    def test_search_populates_translations(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 403
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="dog_src", tag="dog"))
            session.add(
                UserTagTranslationPatch(
                    target_scope="user", target_tag_id=tag_id, language="ja", translation="犬"
                )
            )
            session.commit()

        rows = overlay_reader.search_tags("dog")
        assert rows[0]["translations"] == {"ja": ["犬"]}

    # --- #82: alias / deprecated / type_names filters ---

    def test_alias_false_excludes_alias_tags(self, overlay_reader, overlay_session_factory):
        normal_id = USER_TAG_ID_OFFSET + 410
        alias_id = USER_TAG_ID_OFFSET + 411
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=normal_id, source_tag="f1", tag="filter normal"))
            session.add(UserTag(tag_id=alias_id, source_tag="f2", tag="filter alias"))
            session.add(self._make_status(normal_id, 1000, alias=False))
            session.add(self._make_status(alias_id, 1000, alias=True))
            session.commit()

        rows = overlay_reader.search_tags("filter", partial=True, alias=False)
        ids = {r["tag_id"] for r in rows}
        assert ids == {normal_id}

    def test_alias_true_keeps_only_alias_tags(self, overlay_reader, overlay_session_factory):
        normal_id = USER_TAG_ID_OFFSET + 412
        alias_id = USER_TAG_ID_OFFSET + 413
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=normal_id, source_tag="g1", tag="aliasflag normal"))
            session.add(UserTag(tag_id=alias_id, source_tag="g2", tag="aliasflag alias"))
            session.add(self._make_status(normal_id, 1000, alias=False))
            session.add(self._make_status(alias_id, 1000, alias=True))
            session.commit()

        rows = overlay_reader.search_tags("aliasflag", partial=True, alias=True)
        assert {r["tag_id"] for r in rows} == {alias_id}

    def test_deprecated_false_excludes_deprecated_tags(self, overlay_reader, overlay_session_factory):
        live_id = USER_TAG_ID_OFFSET + 414
        dead_id = USER_TAG_ID_OFFSET + 415
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=live_id, source_tag="h1", tag="depr live"))
            session.add(UserTag(tag_id=dead_id, source_tag="h2", tag="depr dead"))
            session.add(self._make_status(live_id, 1000, deprecated=False))
            session.add(self._make_status(dead_id, 1000, deprecated=True))
            session.commit()

        rows = overlay_reader.search_tags("depr", partial=True, deprecated=False)
        assert {r["tag_id"] for r in rows} == {live_id}

    def test_type_names_filter(self, overlay_reader, overlay_session_factory):
        char_id = USER_TAG_ID_OFFSET + 416
        general_id = USER_TAG_ID_OFFSET + 417
        with overlay_session_factory() as session:
            session.add(TagFormat(format_id=1000, format_name="danbooru"))
            session.add(TagTypeName(type_name_id=1, type_name="general"))
            session.add(TagTypeName(type_name_id=4, type_name="character"))
            session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))
            session.add(TagTypeFormatMapping(format_id=1000, type_id=4, type_name_id=4))
            session.add(UserTag(tag_id=char_id, source_tag="t1", tag="typefilter char"))
            session.add(UserTag(tag_id=general_id, source_tag="t2", tag="typefilter general"))
            session.add(self._make_status(char_id, 1000, type_id=4))
            session.add(self._make_status(general_id, 1000, type_id=0))
            session.commit()

        rows = overlay_reader.search_tags("typefilter", partial=True, type_names=["character"])
        assert {r["tag_id"] for r in rows} == {char_id}
        assert rows[0]["type_name"] == "character"

    def test_type_names_unknown_returns_empty(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 418
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=tag_id, source_tag="u1", tag="unknowntype tag"))
            session.add(self._make_status(tag_id, 1000))
            session.commit()

        assert overlay_reader.search_tags("unknowntype", partial=True, type_names=["nope"]) == []

    # --- #84: usage filters & usage_count ---

    def test_usage_count_populated_for_single_format(self, overlay_reader, overlay_session_factory):
        tag_id = USER_TAG_ID_OFFSET + 420
        with overlay_session_factory() as session:
            session.add(TagFormat(format_id=1000, format_name="danbooru"))
            session.add(UserTag(tag_id=tag_id, source_tag="uc_src", tag="usage tag"))
            session.add(self._make_status(tag_id, 1000))
            session.add(
                UserTagUsagePatch(target_scope="user", target_tag_id=tag_id, format_id=1000, count=123)
            )
            session.commit()

        rows = overlay_reader.search_tags("usage tag", format_name="danbooru")
        assert len(rows) == 1
        assert rows[0]["usage_count"] == 123
        assert rows[0]["format_statuses"]["1000"]["usage_count"] == 123

    def test_min_usage_filters_out_low_counts(self, overlay_reader, overlay_session_factory):
        high_id = USER_TAG_ID_OFFSET + 421
        low_id = USER_TAG_ID_OFFSET + 422
        with overlay_session_factory() as session:
            session.add(TagFormat(format_id=1000, format_name="danbooru"))
            session.add(UserTag(tag_id=high_id, source_tag="m1", tag="minusage high"))
            session.add(UserTag(tag_id=low_id, source_tag="m2", tag="minusage low"))
            session.add(self._make_status(high_id, 1000))
            session.add(self._make_status(low_id, 1000))
            session.add(
                UserTagUsagePatch(target_scope="user", target_tag_id=high_id, format_id=1000, count=500)
            )
            session.add(
                UserTagUsagePatch(target_scope="user", target_tag_id=low_id, format_id=1000, count=5)
            )
            session.commit()

        rows = overlay_reader.search_tags("minusage", partial=True, format_name="danbooru", min_usage=100)
        assert {r["tag_id"] for r in rows} == {high_id}

    def test_max_usage_filters_out_high_counts(self, overlay_reader, overlay_session_factory):
        high_id = USER_TAG_ID_OFFSET + 423
        low_id = USER_TAG_ID_OFFSET + 424
        with overlay_session_factory() as session:
            session.add(TagFormat(format_id=1000, format_name="danbooru"))
            session.add(UserTag(tag_id=high_id, source_tag="x1", tag="maxusage high"))
            session.add(UserTag(tag_id=low_id, source_tag="x2", tag="maxusage low"))
            session.add(self._make_status(high_id, 1000))
            session.add(self._make_status(low_id, 1000))
            session.add(
                UserTagUsagePatch(target_scope="user", target_tag_id=high_id, format_id=1000, count=500)
            )
            session.add(
                UserTagUsagePatch(target_scope="user", target_tag_id=low_id, format_id=1000, count=5)
            )
            session.commit()

        rows = overlay_reader.search_tags("maxusage", partial=True, format_name="danbooru", max_usage=100)
        assert {r["tag_id"] for r in rows} == {low_id}

    def test_language_filter(self, overlay_reader, overlay_session_factory):
        ja_id = USER_TAG_ID_OFFSET + 425
        en_id = USER_TAG_ID_OFFSET + 426
        with overlay_session_factory() as session:
            session.add(UserTag(tag_id=ja_id, source_tag="l1", tag="langfilter ja"))
            session.add(UserTag(tag_id=en_id, source_tag="l2", tag="langfilter en"))
            session.add(
                UserTagTranslationPatch(
                    target_scope="user", target_tag_id=ja_id, language="ja", translation="あ"
                )
            )
            session.add(
                UserTagTranslationPatch(
                    target_scope="user", target_tag_id=en_id, language="en", translation="a"
                )
            )
            session.commit()

        rows = overlay_reader.search_tags("langfilter", partial=True, language="ja")
        assert {r["tag_id"] for r in rows} == {ja_id}

    def test_limit_and_offset_applied_after_filters(self, overlay_reader, overlay_session_factory):
        ids = [USER_TAG_ID_OFFSET + 430 + i for i in range(3)]
        with overlay_session_factory() as session:
            for i, tag_id in enumerate(ids):
                session.add(UserTag(tag_id=tag_id, source_tag=f"p{i}", tag=f"paging tag {i}"))
            session.commit()

        page = overlay_reader.search_tags("paging", partial=True, limit=2, offset=1)
        assert [r["tag_id"] for r in page] == ids[1:3]


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


class TestOverlayTagReaderTypeMethods:
    """get_all_types / get_tag_types / get_unknown_type_tag_ids を検証する (#100)。"""

    def _seed_types(self, session) -> None:
        session.add(TagFormat(format_id=3001, format_name="lorairo"))
        session.add(TagFormat(format_id=3002, format_name="other"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeName(type_name_id=4, type_name="character"))
        session.add(TagTypeName(type_name_id=99, type_name="unknown"))
        # lorairo: general(0) / character(4) / unknown(7)
        session.add(TagTypeFormatMapping(format_id=3001, type_id=0, type_name_id=1))
        session.add(TagTypeFormatMapping(format_id=3001, type_id=4, type_name_id=4))
        session.add(TagTypeFormatMapping(format_id=3001, type_id=7, type_name_id=99))
        # other: general(0) のみ
        session.add(TagTypeFormatMapping(format_id=3002, type_id=0, type_name_id=1))

    def test_get_all_types(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            self._seed_types(session)
            session.commit()

        assert set(overlay_reader.get_all_types()) == {"general", "character", "unknown"}

    def test_get_all_types_empty(self, overlay_reader):
        assert overlay_reader.get_all_types() == []

    def test_get_tag_types_filters_by_format(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            self._seed_types(session)
            session.commit()

        assert set(overlay_reader.get_tag_types(3001)) == {"general", "character", "unknown"}
        assert overlay_reader.get_tag_types(3002) == ["general"]

    def test_get_tag_types_unknown_format(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            self._seed_types(session)
            session.commit()

        assert overlay_reader.get_tag_types(9999) == []

    def test_get_unknown_type_tag_ids(self, overlay_reader, overlay_session_factory):
        unknown_id = USER_TAG_ID_OFFSET + 500
        general_id = USER_TAG_ID_OFFSET + 501
        with overlay_session_factory() as session:
            self._seed_types(session)
            session.add(UserTag(tag_id=unknown_id, source_tag="u_src", tag="unknown tag"))
            session.add(UserTag(tag_id=general_id, source_tag="g_src", tag="general tag"))
            session.add(
                UserTagStatusPatch(
                    target_scope="user",
                    target_tag_id=unknown_id,
                    format_id=3001,
                    type_id=7,  # unknown
                    alias=False,
                    preferred_scope="user",
                    preferred_tag_id=unknown_id,
                    deprecated=False,
                )
            )
            session.add(
                UserTagStatusPatch(
                    target_scope="user",
                    target_tag_id=general_id,
                    format_id=3001,
                    type_id=0,  # general
                    alias=False,
                    preferred_scope="user",
                    preferred_tag_id=general_id,
                    deprecated=False,
                )
            )
            session.commit()

        assert overlay_reader.get_unknown_type_tag_ids(3001) == [unknown_id]

    def test_get_unknown_type_tag_ids_no_unknown_mapping(self, overlay_reader, overlay_session_factory):
        with overlay_session_factory() as session:
            self._seed_types(session)
            session.commit()

        # format 3002 には unknown のマッピングが無い
        assert overlay_reader.get_unknown_type_tag_ids(3002) == []

    def test_get_unknown_type_tag_ids_empty(self, overlay_reader):
        assert overlay_reader.get_unknown_type_tag_ids(3001) == []

    def test_merged_aggregates_type_methods(self, overlay_reader, overlay_session_factory):
        """MergedTagReader 経由でも overlay の type 系メソッドが集約されることを確認する。"""
        unknown_id = USER_TAG_ID_OFFSET + 510
        with overlay_session_factory() as session:
            self._seed_types(session)
            session.add(UserTag(tag_id=unknown_id, source_tag="m_src", tag="merged unknown"))
            session.add(
                UserTagStatusPatch(
                    target_scope="user",
                    target_tag_id=unknown_id,
                    format_id=3001,
                    type_id=7,
                    alias=False,
                    preferred_scope="user",
                    preferred_tag_id=unknown_id,
                    deprecated=False,
                )
            )
            session.commit()

        class _EmptyBase:
            def _empty(self, *a, **k):
                return []

            get_all_types = get_tag_types = get_unknown_type_tag_ids = _empty

            def _iter_repos_marker(self):  # pragma: no cover - not used
                return []

        merged = MergedTagReader(base_repo=_EmptyBase(), user_repo=overlay_reader)
        assert set(merged.get_all_types()) == {"general", "character", "unknown"}
        assert set(merged.get_tag_types(3001)) == {"general", "character", "unknown"}
        assert merged.get_unknown_type_tag_ids(3001) == [unknown_id]


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
