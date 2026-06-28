"""overlay DB 対応の DatabaseMaintenanceTool テスト。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import genai_tag_db_tools.db.db_maintenance_tool as maintenance_module
from genai_tag_db_tools.db.runtime import _create_engine
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTag,
)

# --- fixtures ---


@pytest.fixture()
def base_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """base DB を tmp_path に作成し、タグデータを INSERT する。"""
    db_path = tmp_path / "base.sqlite"
    engine = _create_engine(db_path)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as session:
        session.add(TagTypeName(type_name_id=1, type_name="unknown"))
        session.add(TagFormat(format_id=1, format_name="test_format"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=100, source_tag="cat", tag="cat"))
        session.add(Tag(tag_id=200, source_tag="dog", tag="dog"))
        session.commit()

    engine.dispose()

    # _make_tool が使う runtime 関数をモンキーパッチ
    monkeypatch.setattr(maintenance_module, "set_database_path", lambda p: None)
    monkeypatch.setattr(maintenance_module, "init_engine", lambda p: None)

    # reader.get_all_tag_ids() が base タグ ID を返すように差し替える
    class DummyReader:
        def get_all_tag_ids(self) -> list[int]:
            return [100, 200]

    monkeypatch.setattr(maintenance_module, "get_default_reader", lambda: DummyReader())
    monkeypatch.setattr(maintenance_module, "get_default_repository", lambda: DummyReader())

    return db_path


@pytest.fixture()
def user_db(tmp_path: Path):
    """user DB を tmp_path に作成し、overlay スキーマのみ用意する。"""
    db_path = tmp_path / "user.sqlite"
    engine = _create_engine(db_path)
    UserOverlayBase.metadata.create_all(engine)
    engine.dispose()
    return db_path


def _make_tool(base_db: Path, user_db: Path | None = None) -> maintenance_module.DatabaseMaintenanceTool:
    return maintenance_module.DatabaseMaintenanceTool(
        db_path=str(base_db),
        user_db_path=str(user_db) if user_db is not None else None,
    )


def _insert_user_tag(db_path: Path, tag_id: int, tag: str) -> None:
    engine = _create_engine(db_path)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as session:
        session.add(UserTag(tag_id=tag_id, source_tag=tag, tag=tag))
        session.commit()
    engine.dispose()


def _make_mock_session_factory(*, query_result=None, filter_result=None):
    """session.query().all() および .filter().all() を差し替えるモック。

    CHECK 制約で DB に挿入できない不正データを返すために使う。
    """
    mock_session = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_session)
    mock_cm.__exit__ = MagicMock(return_value=False)

    mock_query = MagicMock()
    mock_query.all.return_value = query_result or []
    mock_query.filter.return_value.all.return_value = filter_result or []
    mock_session.query.return_value = mock_query

    return MagicMock(return_value=mock_cm)


def _insert_patch(db_path: Path, **kwargs) -> None:
    """USER_TAG_STATUS_PATCH を raw SQL で INSERT（CHECK 制約を回避するため）。"""
    engine = _create_engine(db_path)
    defaults = {
        "target_scope": "base",
        "target_tag_id": 100,
        "format_id": 1,
        "type_id": 0,
        "alias": 0,
        "preferred_scope": "base",
        "preferred_tag_id": 100,
        "deprecated": 0,
    }
    defaults.update(kwargs)
    with engine.connect() as conn:
        # SQLite の CHECK 制約は正常な行にのみ通る
        conn.execute(
            text(
                "INSERT INTO USER_TAG_STATUS_PATCH "
                "(target_scope, target_tag_id, format_id, type_id, alias, "
                "preferred_scope, preferred_tag_id, deprecated) "
                "VALUES (:target_scope, :target_tag_id, :format_id, :type_id, :alias, "
                ":preferred_scope, :preferred_tag_id, :deprecated)"
            ),
            defaults,
        )
        conn.commit()
    engine.dispose()


# --- TestDetectOverlayOrphanRecords ---


@pytest.mark.db_tools
class TestDetectOverlayOrphanRecords:
    def test_no_patches_returns_empty(self, base_db, user_db):
        tool = _make_tool(base_db, user_db)
        result = tool.detect_overlay_orphan_records()
        assert result == {"orphan_target": [], "orphan_preferred": []}

    def test_valid_patch_not_in_orphan(self, base_db, user_db):
        """存在するタグを参照する正常パッチは孤立とならない。"""
        _insert_patch(user_db, target_scope="base", target_tag_id=100, preferred_tag_id=100)
        tool = _make_tool(base_db, user_db)
        result = tool.detect_overlay_orphan_records()
        assert result["orphan_target"] == []
        assert result["orphan_preferred"] == []

    def test_nonexistent_base_target_detected(self, base_db, user_db):
        """base TAGS に存在しない target_tag_id を持つパッチを検出する。"""
        _insert_patch(user_db, target_scope="base", target_tag_id=999, preferred_tag_id=999)
        tool = _make_tool(base_db, user_db)
        result = tool.detect_overlay_orphan_records()
        assert len(result["orphan_target"]) == 1
        assert result["orphan_target"][0]["target_tag_id"] == 999
        assert "base TAGS" in result["orphan_target"][0]["reason"]

    def test_nonexistent_user_target_detected(self, base_db, user_db):
        """USER_TAGS に存在しない target_tag_id (user scope) を検出する。"""
        # user タグなし; USER_TAG_ID_OFFSET+999 は存在しない
        _insert_patch(
            user_db,
            target_scope="user",
            target_tag_id=USER_TAG_ID_OFFSET + 999,
            preferred_scope="user",
            preferred_tag_id=USER_TAG_ID_OFFSET + 999,
        )
        tool = _make_tool(base_db, user_db)
        result = tool.detect_overlay_orphan_records()
        assert len(result["orphan_target"]) == 1
        assert "USER_TAGS" in result["orphan_target"][0]["reason"]

    def test_nonexistent_preferred_detected(self, base_db, user_db):
        """base TAGS に存在しない preferred_tag_id を持つパッチを検出する。"""
        # alias patch: target=100 (exists), preferred=888 (not exists)
        _insert_patch(
            user_db,
            target_scope="base",
            target_tag_id=100,
            alias=1,
            preferred_scope="base",
            preferred_tag_id=888,
        )
        tool = _make_tool(base_db, user_db)
        result = tool.detect_overlay_orphan_records()
        assert result["orphan_target"] == []
        assert len(result["orphan_preferred"]) == 1
        assert result["orphan_preferred"][0]["preferred_tag_id"] == 888

    def test_user_tag_as_target_valid(self, base_db, user_db):
        """USER_TAGS に存在する user タグを target にしたパッチは孤立にならない。"""
        uid = USER_TAG_ID_OFFSET + 1
        _insert_user_tag(user_db, uid, "my_tag")
        _insert_patch(
            user_db,
            target_scope="user",
            target_tag_id=uid,
            preferred_scope="user",
            preferred_tag_id=uid,
        )
        tool = _make_tool(base_db, user_db)
        result = tool.detect_overlay_orphan_records()
        assert result["orphan_target"] == []


# --- TestDetectOverlayInconsistentAlias ---


@pytest.mark.db_tools
class TestDetectOverlayInconsistentAlias:
    def test_no_patches_returns_empty(self, base_db, user_db):
        tool = _make_tool(base_db, user_db)
        assert tool.detect_overlay_inconsistent_alias() == []

    def test_valid_non_alias_patch_not_detected(self, base_db, user_db):
        """alias=False かつ preferred==self は正常。"""
        _insert_patch(user_db, alias=0, preferred_tag_id=100)
        tool = _make_tool(base_db, user_db)
        assert tool.detect_overlay_inconsistent_alias() == []

    def test_valid_alias_patch_not_detected(self, base_db, user_db):
        """alias=True かつ preferred!=self は正常。"""
        _insert_patch(user_db, alias=1, preferred_tag_id=200)
        tool = _make_tool(base_db, user_db)
        assert tool.detect_overlay_inconsistent_alias() == []

    def test_non_alias_with_different_preferred_detected(self, base_db, user_db):
        """alias=False なのに preferred が自分自身でない行を検出する。

        SQLite の CHECK 制約でこの不正データは DB に挿入できないため、
        セッションファクトリをモックして application 層の検出ロジックを検証する。
        """
        fake_patch = SimpleNamespace(
            target_scope="base",
            target_tag_id=100,
            format_id=1,
            alias=False,
            preferred_scope="base",
            preferred_tag_id=200,
        )
        tool = _make_tool(base_db, user_db)
        tool._user_session_factory = _make_mock_session_factory(query_result=[fake_patch])

        result = tool.detect_overlay_inconsistent_alias()
        assert len(result) == 1
        assert "alias=False" in result[0]["reason"]

    def test_alias_pointing_to_self_detected(self, base_db, user_db):
        """alias=True なのに preferred が自分自身を指す行を検出する。

        SQLite の CHECK 制約でこの不正データは DB に挿入できないため、
        セッションファクトリをモックして application 層の検出ロジックを検証する。
        """
        fake_patch = SimpleNamespace(
            target_scope="base",
            target_tag_id=100,
            format_id=1,
            alias=True,
            preferred_scope="base",
            preferred_tag_id=100,
        )
        tool = _make_tool(base_db, user_db)
        tool._user_session_factory = _make_mock_session_factory(query_result=[fake_patch])

        result = tool.detect_overlay_inconsistent_alias()
        assert len(result) == 1
        assert "alias=True" in result[0]["reason"]


# --- TestDetectUserTagIdRange ---


@pytest.mark.db_tools
class TestDetectUserTagIdRange:
    def test_no_user_tags_returns_empty(self, base_db, user_db):
        tool = _make_tool(base_db, user_db)
        assert tool.detect_user_tag_id_range() == []

    def test_valid_user_tag_not_detected(self, base_db, user_db):
        """オフセット以上の tag_id は違反にならない。"""
        _insert_user_tag(user_db, USER_TAG_ID_OFFSET + 1, "valid_tag")
        tool = _make_tool(base_db, user_db)
        assert tool.detect_user_tag_id_range() == []

    def test_below_offset_detected_via_mock(self, base_db, user_db):
        """offset 未満の tag_id を持つ UserTag を検出する。

        SQLite の CHECK 制約でこの不正データは DB に挿入できないため、
        セッションファクトリをモックして application 層の検出ロジックを検証する。
        """
        fake_tag = SimpleNamespace(tag_id=999, tag="x")
        tool = _make_tool(base_db, user_db)
        tool._user_session_factory = _make_mock_session_factory(filter_result=[fake_tag])

        result = tool.detect_user_tag_id_range()
        assert len(result) == 1
        assert result[0]["tag_id"] == 999
        assert "USER_TAG_ID_OFFSET" in result[0]["reason"]


# --- TestNoUserDb ---


@pytest.mark.db_tools
class TestNoUserDb:
    def test_detect_overlay_orphan_records_no_user_db(self, base_db):
        """user_db_path=None のとき detect_overlay_orphan_records は空を返す。"""
        tool = _make_tool(base_db, None)
        result = tool.detect_overlay_orphan_records()
        assert result == {"orphan_target": [], "orphan_preferred": []}

    def test_detect_overlay_inconsistent_alias_no_user_db(self, base_db):
        """user_db_path=None のとき detect_overlay_inconsistent_alias は空を返す。"""
        tool = _make_tool(base_db, None)
        assert tool.detect_overlay_inconsistent_alias() == []

    def test_detect_user_tag_id_range_no_user_db(self, base_db):
        """user_db_path=None のとき detect_user_tag_id_range は空を返す。"""
        tool = _make_tool(base_db, None)
        assert tool.detect_user_tag_id_range() == []
