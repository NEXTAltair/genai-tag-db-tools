"""MergedTagReader の case-variant user 重複 dedup テスト (#1223 / #1212)。

user が独自登録した「base タグの大文字小文字違い重複」(例: base ``anime`` に対する
user ``Anime``) が resolve_preferred 解決経路で base canonical を覆い隠さないことを
検証する。別文字列の user alias (#1183) や deprecated base タグ (#1212) の解決は
壊さない。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

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

_DANBOORU_FORMAT_ID = 1
_LORAIRO_FORMAT_ID = 1000
_BASE_ANIME_ID = 166991
_USER_ANIME_ID = USER_TAG_ID_OFFSET + 11756


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def base_session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'base.sqlite'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def user_session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'user.sqlite'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    UserOverlayBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def populated_base(base_session_factory):
    """Base DB に deprecated な danbooru タグ ``anime`` を挿入する。"""
    with base_session_factory() as session:
        session.add(TagFormat(format_id=_DANBOORU_FORMAT_ID, format_name="danbooru"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=_DANBOORU_FORMAT_ID, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=_BASE_ANIME_ID, source_tag="anime", tag="anime"))
        session.flush()
        session.add(
            TagStatus(
                tag_id=_BASE_ANIME_ID,
                format_id=_DANBOORU_FORMAT_ID,
                type_id=0,
                alias=False,
                preferred_tag_id=_BASE_ANIME_ID,
                deprecated=True,
            )
        )
        session.commit()


@pytest.fixture
def populated_user_case_dup(user_session_factory):
    """User DB に base ``anime`` の case 重複 ``Anime`` (非 alias / 非 deprecated) を挿入する。"""
    with user_session_factory() as session:
        session.add(UserTag(tag_id=_USER_ANIME_ID, source_tag="Anime", tag="Anime"))
        session.flush()
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=_USER_ANIME_ID,
                format_id=_LORAIRO_FORMAT_ID,
                type_id=0,
                alias=False,
                preferred_scope="user",
                preferred_tag_id=_USER_ANIME_ID,
                deprecated=False,
            )
        )
        session.commit()


@pytest.fixture
def merged(base_session_factory, user_session_factory, populated_base, populated_user_case_dup):
    base_repo = TagReader(session_factory=base_session_factory)
    user_repo = OverlayTagReader(session_factory=user_session_factory)
    return MergedTagReader(base_repo=base_repo, user_repo=user_repo)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestCaseVariantUserDedup:
    """resolve_preferred 経路で user case 重複が base canonical を覆い隠さない。"""

    def test_stage1_nondeprecated_danbooru_drops_user_dup(self, merged):
        """LoRAIro stage1 相当: 非 deprecated danbooru では user ``Anime`` を返さない。

        base ``anime`` は deprecated で除外され、user ``Anime`` は case 重複として
        dedup されるため結果は空になる (呼び出し側は次段へフォールバックできる)。
        """
        rows = merged.search_tags(
            "anime",
            format_names=["danbooru"],
            deprecated=False,
            resolve_preferred=True,
        )
        assert all(row["tag_id"] < USER_TAG_ID_OFFSET for row in rows)
        assert rows == []

    def test_stage3_deprecated_included_returns_base_canonical(self, merged):
        """LoRAIro stage3 相当: deprecated 込みなら base ``anime`` (166991) を返す。"""
        rows = merged.search_tags(
            "anime",
            format_names=["danbooru"],
            resolve_preferred=True,
        )
        assert len(rows) == 1
        assert rows[0]["tag_id"] == _BASE_ANIME_ID
        assert rows[0]["tag"] == "anime"

    def test_browsing_without_resolve_preferred_keeps_user_dup(self, merged):
        """resolve_preferred=False (ブラウズ) では dedup せず user ``Anime`` を残す。"""
        rows = merged.search_tags("anime", deprecated=False, resolve_preferred=False)
        assert any(row["tag_id"] == _USER_ANIME_ID for row in rows)


class TestUserAliasNotDeduped:
    """別文字列の user alias (#1183) は case dedup 対象外。"""

    @pytest.fixture
    def merged_alias(self, base_session_factory, user_session_factory, populated_base):
        # base ``anime`` に対する user alias ``aniime`` (typo, 別文字列)。
        with user_session_factory() as session:
            alias_id = USER_TAG_ID_OFFSET + 5000
            session.add(UserTag(tag_id=alias_id, source_tag="aniime", tag="aniime"))
            session.flush()
            session.add(
                UserTagStatusPatch(
                    target_scope="user",
                    target_tag_id=alias_id,
                    format_id=_LORAIRO_FORMAT_ID,
                    type_id=0,
                    alias=True,
                    preferred_scope="base",
                    preferred_tag_id=_BASE_ANIME_ID,
                    deprecated=False,
                )
            )
            session.commit()
        base_repo = TagReader(session_factory=base_session_factory)
        user_repo = OverlayTagReader(session_factory=user_session_factory)
        return MergedTagReader(base_repo=base_repo, user_repo=user_repo)

    def test_different_string_alias_resolves_to_base(self, merged_alias):
        """``aniime`` は base ``anime`` の case 重複ではないため alias→preferred 解決が生きる。"""
        rows = merged_alias.search_tags("aniime", resolve_preferred=True)
        assert len(rows) == 1
        assert rows[0]["tag_id"] == _BASE_ANIME_ID
        assert rows[0]["tag"] == "anime"
