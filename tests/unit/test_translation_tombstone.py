"""翻訳 overlay の削除・tombstone (base 翻訳の抑制) の単体テスト (#121)。

- UserTagRepository: patch 行削除 / tombstone の書き込み・取り消し
- OverlayTagReader: tombstone 済み patch 行の除外
- MergedTagReader: base 由来翻訳の抑制 (get_translations* / 主訳 / search 行マージ)
- TagRepository: scope 解決つき公開経路 (delete_user_translation / suppress_translation)
- 言語付け替え (旧言語 tombstone + 新言語 patch) の end-to-end
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagTranslation,
    UserOverlayBase,
    UserTagTranslationPatch,
    UserTagTranslationTombstone,
)
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

pytestmark = pytest.mark.db_tools

# --- fixtures ---


@pytest.fixture()
def user_engine(tmp_path: Path):
    """tmp_path に Base + UserOverlayBase 両スキーマを持つ SQLite エンジン。"""
    db_path = tmp_path / "test_tombstone.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def user_session_factory(user_engine):
    return sessionmaker(bind=user_engine, autoflush=False, autocommit=False)


@pytest.fixture()
def user_repo(user_session_factory):
    return UserTagRepository(user_session_factory)


@pytest.fixture()
def overlay_reader(user_session_factory):
    return OverlayTagReader(session_factory=user_session_factory)


@pytest.fixture()
def merged(user_session_factory, overlay_reader):
    """base (TAGS/TAG_TRANSLATIONS) + user overlay を合成した MergedTagReader。"""
    return MergedTagReader(
        base_repo=TagReader(session_factory=user_session_factory),
        user_repo=overlay_reader,
    )


def _add_base_translation(session_factory, tag_id: int, language: str, translation: str) -> None:
    """base 側 (TAG_TRANSLATIONS) に翻訳行を作る。"""
    with session_factory() as session:
        if session.get(Tag, tag_id) is None:
            session.add(Tag(tag_id=tag_id, source_tag=f"tag{tag_id}", tag=f"tag{tag_id}"))
        session.add(TagTranslation(tag_id=tag_id, language=language, translation=translation))
        session.commit()


# --- UserTagRepository ---


class TestDeleteTranslationPatch:
    def test_delete_returns_true_then_false(self, user_repo, user_session_factory):
        user_repo.write_translation_patch("base", 10, "ja", "誤った訳")

        assert user_repo.delete_translation_patch("base", 10, "ja", "誤った訳") is True
        assert user_repo.delete_translation_patch("base", 10, "ja", "誤った訳") is False
        with user_session_factory() as session:
            assert session.query(UserTagTranslationPatch).count() == 0

    def test_delete_leaves_other_rows(self, user_repo, user_session_factory):
        user_repo.write_translation_patch("base", 10, "ja", "訳A")
        user_repo.write_translation_patch("base", 10, "ja", "訳B")

        assert user_repo.delete_translation_patch("base", 10, "ja", "訳A") is True
        with user_session_factory() as session:
            rows = session.query(UserTagTranslationPatch).all()
        assert [(r.language, r.translation) for r in rows] == [("ja", "訳B")]


class TestTranslationTombstoneWrites:
    def test_write_is_idempotent(self, user_repo, user_session_factory):
        user_repo.write_translation_tombstone("base", 10, "ja", "隠す訳")
        user_repo.write_translation_tombstone("base", 10, "ja", "隠す訳")

        with user_session_factory() as session:
            assert session.query(UserTagTranslationTombstone).count() == 1

    def test_delete_returns_true_then_false(self, user_repo):
        user_repo.write_translation_tombstone("base", 10, "ja", "隠す訳")

        assert user_repo.delete_translation_tombstone("base", 10, "ja", "隠す訳") is True
        assert user_repo.delete_translation_tombstone("base", 10, "ja", "隠す訳") is False


# --- OverlayTagReader ---


class TestOverlayReaderTombstoneExclusion:
    def test_tombstoned_patch_row_is_hidden(self, user_repo, overlay_reader):
        user_repo.write_translation_patch("base", 10, "ja", "誤った訳")
        user_repo.write_translation_patch("base", 10, "ja", "正しい訳")
        user_repo.write_translation_tombstone("base", 10, "ja", "誤った訳")

        single = [(t.language, t.translation) for t in overlay_reader.get_translations(10)]
        batch = overlay_reader.get_translations_batch([10])

        assert single == [("ja", "正しい訳")]
        assert [(t.language, t.translation) for t in batch[10]] == [("ja", "正しい訳")]

    def test_get_translation_tombstones_batch(self, user_repo, overlay_reader):
        user_repo.write_translation_tombstone("base", 10, "ja", "隠す訳")
        user_repo.write_translation_tombstone("base", 20, "en", "hidden")

        result = overlay_reader.get_translation_tombstones_batch([10, 20, 30])

        assert result == {10: {("ja", "隠す訳")}, 20: {("en", "hidden")}}
        assert overlay_reader.get_translation_tombstones_batch([]) == {}


# --- MergedTagReader ---


class TestMergedReaderSuppression:
    def test_base_translation_is_suppressed(self, user_repo, user_session_factory, merged):
        _add_base_translation(user_session_factory, 10, "ja", "誤った訳")
        _add_base_translation(user_session_factory, 10, "en", "correct")
        user_repo.write_translation_tombstone("base", 10, "ja", "誤った訳")

        batch = merged.get_translations_batch([10])
        single = merged.get_translations(10)

        assert [(t.language, t.translation) for t in batch[10]] == [("en", "correct")]
        assert [(t.language, t.translation) for t in single] == [("en", "correct")]

    def test_without_user_repo_nothing_is_suppressed(self, user_session_factory):
        _add_base_translation(user_session_factory, 10, "ja", "訳")
        merged = MergedTagReader(base_repo=TagReader(session_factory=user_session_factory))

        batch = merged.get_translations_batch([10])

        assert [(t.language, t.translation) for t in batch[10]] == [("ja", "訳")]

    def test_preferred_translation_is_suppressed(self, user_repo, overlay_reader, merged):
        user_repo.write_translation_preference("base", 10, "ja", "隠す主訳")
        user_repo.write_translation_tombstone("base", 10, "ja", "隠す主訳")

        assert merged.get_preferred_translations_batch([10]) == {}

    def test_search_row_translations_are_suppressed(self, user_repo, merged):
        # base 検索行に載ってきた翻訳が _apply_user_patches_to_search_rows の
        # マージ時に除外されること (#121。search_tags 本体の行構築は既存テストが担う)
        user_repo.write_translation_tombstone("base", 10, "ja", "誤った訳")
        row = {
            "tag_id": 10,
            "tag": "tag10",
            "translations": {"ja": ["誤った訳", "正しい訳"], "en": ["ok"]},
            "format_statuses": {},
        }

        patched = merged._apply_user_patches_to_search_rows([row])

        assert patched[0]["translations"] == {"ja": ["正しい訳"], "en": ["ok"]}


# --- TagRepository 公開経路 (scope 解決) ---


class TestTagRepositoryPublicPath:
    def test_delete_user_translation_via_heuristic_scope(self, user_session_factory, overlay_reader):
        repo = TagRepository(user_session_factory)
        user_tag_id = USER_TAG_ID_OFFSET + 5
        repo.write_user_translation(user_tag_id, "ja", "訳")
        assert [(t.language, t.translation) for t in overlay_reader.get_translations(user_tag_id)] == [
            ("ja", "訳")
        ]

        assert repo.delete_user_translation(user_tag_id, "ja", "訳") is True
        assert overlay_reader.get_translations(user_tag_id) == []
        assert repo.delete_user_translation(user_tag_id, "ja", "訳") is False

    def test_suppress_and_unsuppress_translation(self, user_session_factory, merged):
        repo = TagRepository(user_session_factory)
        _add_base_translation(user_session_factory, 10, "ja", "誤った訳")

        repo.suppress_translation(10, "ja", "誤った訳")
        assert merged.get_translations_batch([10]) == {}

        assert repo.unsuppress_translation(10, "ja", "誤った訳") is True
        batch = merged.get_translations_batch([10])
        assert [(t.language, t.translation) for t in batch[10]] == [("ja", "誤った訳")]
        assert repo.unsuppress_translation(10, "ja", "誤った訳") is False


# --- 言語付け替え (issue の期待 API 3) ---


class TestLanguageReassignment:
    def test_tombstone_plus_new_language_patch(self, user_session_factory, user_repo, merged):
        """ja に混入した中国語を zh へ付け替える: 旧行 tombstone + 新言語 patch。"""
        repo = TagRepository(user_session_factory)
        _add_base_translation(user_session_factory, 10, "ja", "错误")

        repo.suppress_translation(10, "ja", "错误")
        repo.write_user_translation(10, "zh", "错误")

        batch = merged.get_translations_batch([10])
        assert [(t.language, t.translation) for t in batch[10]] == [("zh", "错误")]
