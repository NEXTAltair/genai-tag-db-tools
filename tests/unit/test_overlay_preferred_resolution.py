"""MergedTagReader の cross-scope preferred 解決テスト。

user alias → base preferred の cross-scope 解決が機能することを検証する。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.core_api import convert_tags
from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
)

# テスト用定数
_BASE_TAG_ID_BLUE_EYES = 100
_USER_TAG_ID_BLU_EYES = USER_TAG_ID_OFFSET + 100
_USER_TAG_ID_PREFERRED = USER_TAG_ID_OFFSET + 200
_FORMAT_ID = 1000


# ------------------------------------------------------------------
# Fixtures: Base DB
# ------------------------------------------------------------------


@pytest.fixture
def base_engine(tmp_path: Path):
    """Base DB テーブルを持つ SQLite エンジン。"""
    db_path = tmp_path / "base.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def base_session_factory(base_engine):
    return sessionmaker(bind=base_engine, autoflush=False, autocommit=False)


@pytest.fixture
def populated_base(base_session_factory):
    """Base DB に blue eyes タグと TAG_STATUS を挿入する。"""
    with base_session_factory() as session:
        session.add(TagFormat(format_id=_FORMAT_ID, format_name="test_format"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=_FORMAT_ID, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=_BASE_TAG_ID_BLUE_EYES, source_tag="blue_eyes", tag="blue eyes"))
        session.flush()
        session.add(
            TagStatus(
                tag_id=_BASE_TAG_ID_BLUE_EYES,
                format_id=_FORMAT_ID,
                type_id=0,
                alias=False,
                preferred_tag_id=_BASE_TAG_ID_BLUE_EYES,
            )
        )
        session.commit()


# ------------------------------------------------------------------
# Fixtures: User DB
# ------------------------------------------------------------------


@pytest.fixture
def user_engine(tmp_path: Path):
    """User overlay DB テーブルを持つ SQLite エンジン。"""
    db_path = tmp_path / "user.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    UserOverlayBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def user_session_factory(user_engine):
    return sessionmaker(bind=user_engine, autoflush=False, autocommit=False)


@pytest.fixture
def populated_user_cross_scope(user_session_factory):
    """User DB に blu eyes → base blue eyes の cross-scope alias を挿入する。"""
    with user_session_factory() as session:
        session.add(UserTag(tag_id=_USER_TAG_ID_BLU_EYES, source_tag="blu_eyes", tag="blu eyes"))
        session.flush()
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=_USER_TAG_ID_BLU_EYES,
                format_id=_FORMAT_ID,
                type_id=0,
                alias=True,
                preferred_scope="base",
                preferred_tag_id=_BASE_TAG_ID_BLUE_EYES,
                deprecated=False,
            )
        )
        session.commit()


@pytest.fixture
def populated_user_user_scope(user_session_factory):
    """User DB に user→user alias を挿入する。"""
    with user_session_factory() as session:
        # alias タグ
        session.add(UserTag(tag_id=_USER_TAG_ID_BLU_EYES, source_tag="alias_src", tag="alias tag"))
        # preferred タグ
        session.add(UserTag(tag_id=_USER_TAG_ID_PREFERRED, source_tag="preferred_src", tag="preferred tag"))
        session.flush()
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=_USER_TAG_ID_BLU_EYES,
                format_id=_FORMAT_ID,
                type_id=0,
                alias=True,
                preferred_scope="user",
                preferred_tag_id=_USER_TAG_ID_PREFERRED,
                deprecated=False,
            )
        )
        session.commit()


# ------------------------------------------------------------------
# Fixtures: MergedTagReader
# ------------------------------------------------------------------


@pytest.fixture
def merged_reader_cross_scope(
    base_session_factory, user_session_factory, populated_base, populated_user_cross_scope
):
    """Base + user cross-scope alias を持つ MergedTagReader。"""
    base_repo = TagReader(session_factory=base_session_factory)
    user_repo = OverlayTagReader(session_factory=user_session_factory)
    return MergedTagReader(base_repo=base_repo, user_repo=user_repo)


@pytest.fixture
def merged_reader_user_scope(
    base_session_factory, user_session_factory, populated_base, populated_user_user_scope
):
    """Base + user→user alias を持つ MergedTagReader。"""
    base_repo = TagReader(session_factory=base_session_factory)
    user_repo = OverlayTagReader(session_factory=user_session_factory)
    return MergedTagReader(base_repo=base_repo, user_repo=user_repo)


# ------------------------------------------------------------------
# Tests: cross-scope preferred 解決
# ------------------------------------------------------------------


class TestCrossScopePreferredResolution:
    """user alias → base preferred の cross-scope 解決テスト。"""

    def test_search_tags_resolve_preferred_returns_base_tag(self, merged_reader_cross_scope):
        """resolve_preferred=True のとき user alias が base preferred に差し替えられる。"""
        rows = merged_reader_cross_scope.search_tags("blu eyes", resolve_preferred=True)

        assert len(rows) == 1
        assert rows[0]["tag"] == "blue eyes"
        assert rows[0]["tag_id"] == _BASE_TAG_ID_BLUE_EYES
        assert rows[0]["alias"] is False

    def test_search_tags_no_resolve_preferred_returns_alias(self, merged_reader_cross_scope):
        """resolve_preferred=False のとき user alias タグがそのまま返る。"""
        rows = merged_reader_cross_scope.search_tags("blu eyes", resolve_preferred=False)

        assert len(rows) == 1
        assert rows[0]["tag"] == "blu eyes"
        assert rows[0]["tag_id"] == _USER_TAG_ID_BLU_EYES
        assert rows[0]["alias"] is True

    def test_non_alias_row_unchanged_with_resolve_preferred(self, merged_reader_cross_scope):
        """alias=False の行は resolve_preferred=True でも変更されない。"""
        rows = merged_reader_cross_scope.search_tags("blue eyes", resolve_preferred=True)

        assert len(rows) == 1
        assert rows[0]["tag"] == "blue eyes"
        assert rows[0]["alias"] is False

    def test_search_tags_user_to_user_alias_resolved(self, merged_reader_user_scope):
        """user→user alias でも preferred が正しく解決される。"""
        rows = merged_reader_user_scope.search_tags("alias tag", resolve_preferred=True)

        assert len(rows) == 1
        assert rows[0]["tag"] == "preferred tag"
        assert rows[0]["tag_id"] == _USER_TAG_ID_PREFERRED
        assert rows[0]["alias"] is False


# ------------------------------------------------------------------
# Tests: convert_tags での cross-scope alias 変換
# ------------------------------------------------------------------


class TestConvertTagsCrossScope:
    """convert_tags が cross-scope alias を通じてタグを変換するテスト。"""

    def test_convert_alias_to_base_preferred(self, merged_reader_cross_scope):
        """blu_eyes (user alias) が blue eyes (base preferred) に変換される。

        TagCleaner.clean_format がアンダーバーをスペースに変換するため
        入力 "blu_eyes" は "blu eyes" として検索され、cross-scope 解決が行われる。
        """
        result = convert_tags(merged_reader_cross_scope, "blu_eyes", "test_format")

        assert result == "blue eyes"

    def test_convert_non_alias_tag_unchanged(self, merged_reader_cross_scope):
        """alias でないタグはそのまま変換される。"""
        result = convert_tags(merged_reader_cross_scope, "blue_eyes", "test_format")

        assert result == "blue eyes"
