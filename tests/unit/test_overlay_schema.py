"""Tests for overlay DB schema: UserTag, UserTagStatusPatch, TagRef."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
)
from genai_tag_db_tools.db.runtime import _create_engine
from genai_tag_db_tools.models import TagRef


# --- fixtures ---


@pytest.fixture()
def overlay_engine(tmp_path: Path):
    """インメモリ代わりに tmp_path の SQLite で overlay schema を作成する。"""
    db_path = tmp_path / "overlay_test.sqlite"
    engine = _create_engine(db_path)
    UserOverlayBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def overlay_session(overlay_engine):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=overlay_engine, autoflush=False, autocommit=False)
    with Session() as session:
        yield session


# --- TagRef ---


class TestTagRef:
    def test_base_scope(self):
        ref = TagRef(scope="base", tag_id=100)
        assert ref.scope == "base"
        assert ref.tag_id == 100

    def test_user_scope(self):
        ref = TagRef(scope="user", tag_id=USER_TAG_ID_OFFSET + 1)
        assert ref.scope == "user"

    def test_invalid_scope_raises(self):
        with pytest.raises(ValidationError):
            TagRef(scope="other", tag_id=1)

    def test_frozen_prevents_mutation(self):
        ref = TagRef(scope="base", tag_id=1)
        with pytest.raises(ValidationError):
            ref.tag_id = 999  # type: ignore[misc]

    def test_hashable_as_dict_key(self):
        ref = TagRef(scope="base", tag_id=42)
        d = {ref: "value"}
        assert d[ref] == "value"

    def test_equality(self):
        assert TagRef(scope="base", tag_id=1) == TagRef(scope="base", tag_id=1)
        assert TagRef(scope="base", tag_id=1) != TagRef(scope="user", tag_id=1)


# --- overlay schema 作成確認 ---


class TestOverlaySchemaCreation:
    def test_user_tags_table_exists(self, overlay_engine):
        inspector = inspect(overlay_engine)
        assert "USER_TAGS" in inspector.get_table_names()

    def test_user_tag_status_patch_table_exists(self, overlay_engine):
        inspector = inspect(overlay_engine)
        assert "USER_TAG_STATUS_PATCH" in inspector.get_table_names()

    def test_user_tags_columns(self, overlay_engine):
        inspector = inspect(overlay_engine)
        cols = {c["name"] for c in inspector.get_columns("USER_TAGS")}
        assert {"tag_id", "source_tag", "tag", "created_at", "updated_at"} <= cols

    def test_patch_columns(self, overlay_engine):
        inspector = inspect(overlay_engine)
        cols = {c["name"] for c in inspector.get_columns("USER_TAG_STATUS_PATCH")}
        assert {
            "target_scope", "target_tag_id", "format_id",
            "type_id", "alias", "preferred_scope", "preferred_tag_id",
            "deprecated",
        } <= cols


# --- USER_TAGS 制約 ---


class TestUserTagConstraints:
    def test_insert_valid_user_tag(self, overlay_session):
        tag = UserTag(tag_id=USER_TAG_ID_OFFSET + 1, source_tag="my_tag", tag="my_tag")
        overlay_session.add(tag)
        overlay_session.commit()
        assert overlay_session.get(UserTag, USER_TAG_ID_OFFSET + 1) is not None

    def test_tag_id_below_offset_rejected(self, overlay_session):
        tag = UserTag(tag_id=999, source_tag="x", tag="x")
        overlay_session.add(tag)
        with pytest.raises(IntegrityError):
            overlay_session.commit()

    def test_unique_tag_constraint(self, overlay_session):
        overlay_session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 1, source_tag="a", tag="dup"))
        overlay_session.add(UserTag(tag_id=USER_TAG_ID_OFFSET + 2, source_tag="b", tag="dup"))
        with pytest.raises(IntegrityError):
            overlay_session.commit()


# --- USER_TAG_STATUS_PATCH 制約 ---


class TestUserTagStatusPatchConstraints:
    def _non_alias_patch(self, **kwargs) -> UserTagStatusPatch:
        base = dict(
            target_scope="base",
            target_tag_id=100,
            format_id=1000,
            type_id=0,
            alias=False,
            preferred_scope="base",
            preferred_tag_id=100,
            deprecated=False,
        )
        base.update(kwargs)
        return UserTagStatusPatch(**base)

    def _alias_patch(self, **kwargs) -> UserTagStatusPatch:
        base = dict(
            target_scope="base",
            target_tag_id=100,
            format_id=1000,
            type_id=0,
            alias=True,
            preferred_scope="base",
            preferred_tag_id=200,
            deprecated=False,
        )
        base.update(kwargs)
        return UserTagStatusPatch(**base)

    def test_insert_valid_non_alias_patch(self, overlay_session):
        overlay_session.add(self._non_alias_patch())
        overlay_session.commit()

    def test_insert_valid_alias_patch(self, overlay_session):
        overlay_session.add(self._alias_patch())
        overlay_session.commit()

    def test_insert_cross_scope_alias_patch(self, overlay_session):
        """user tag が base tag を preferred に持つ cross-scope alias。"""
        patch = UserTagStatusPatch(
            target_scope="user",
            target_tag_id=USER_TAG_ID_OFFSET + 1,
            format_id=1000,
            type_id=0,
            alias=True,
            preferred_scope="base",
            preferred_tag_id=100,
            deprecated=False,
        )
        overlay_session.add(patch)
        overlay_session.commit()

    def test_composite_pk_duplicate_rejected(self, overlay_session):
        overlay_session.add(self._non_alias_patch())
        overlay_session.commit()
        overlay_session.add(self._non_alias_patch())
        with pytest.raises(IntegrityError):
            overlay_session.commit()

    def test_invalid_target_scope_rejected(self, overlay_session):
        patch = self._non_alias_patch(target_scope="other")
        overlay_session.add(patch)
        with pytest.raises(IntegrityError):
            overlay_session.commit()

    def test_non_alias_with_different_preferred_rejected(self, overlay_session):
        """非 alias なのに preferred が自分自身でない場合は拒否される。"""
        patch = self._non_alias_patch(alias=False, preferred_tag_id=999)
        overlay_session.add(patch)
        with pytest.raises(IntegrityError):
            overlay_session.commit()

    def test_alias_pointing_to_self_rejected(self, overlay_session):
        """alias なのに preferred が自分自身を指す場合は拒否される。"""
        patch = self._alias_patch(alias=True, preferred_tag_id=100)
        overlay_session.add(patch)
        with pytest.raises(IntegrityError):
            overlay_session.commit()


# --- init_user_db でも overlay が作成される ---


class TestInitUserDbCreatesOverlay:
    def test_init_user_db_creates_overlay_tables(self, tmp_path: Path):
        from genai_tag_db_tools.db import runtime

        runtime.close_all()
        user_db_dir = tmp_path / "user_db"
        user_db_dir.mkdir()

        # base DB paths が必要なので minimal base DB を用意
        base_db = tmp_path / "base.sqlite"
        from genai_tag_db_tools.db.schema import Base

        base_engine = _create_engine(base_db)
        Base.metadata.create_all(base_engine)
        base_engine.dispose()

        runtime.set_base_database_paths([base_db])
        runtime.init_engine(base_db)
        runtime.init_user_db(user_db_dir, format_name="TestApp")

        user_engine = _create_engine(user_db_dir / "user_tags.sqlite")
        inspector = inspect(user_engine)
        tables = inspector.get_table_names()
        user_engine.dispose()
        runtime.close_all()

        assert "USER_TAGS" in tables
        assert "USER_TAG_STATUS_PATCH" in tables
