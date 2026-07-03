"""主訳 (優先翻訳) の永続化と取得のテスト (#122)。

USER_TAG_TRANSLATION_PREFERENCE への upsert / 削除 / batch 取得と、
TagRepository の scope 解決、MergedTagReader の delegate を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.core_api import (
    clear_preferred_translation,
    get_preferred_translations_batch,
    set_preferred_translation,
)
from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.runtime import _create_engine
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    UserOverlayBase,
    UserTagTranslationPreference,
)
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository

# --- fixtures ---


@pytest.fixture()
def user_engine(tmp_path: Path):
    db_path = tmp_path / "user_test.sqlite"
    engine = _create_engine(db_path)
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


# --- UserTagRepository: upsert / delete ---


class TestWriteTranslationPreference:
    def test_insert_and_read(self, user_repo, user_session_factory):
        user_repo.write_translation_preference("base", 10, "ja", "青い目")

        with user_session_factory() as session:
            rows = session.query(UserTagTranslationPreference).all()
            assert [(r.target_tag_id, r.language, r.translation) for r in rows] == [(10, "ja", "青い目")]

    def test_upsert_overwrites_same_language(self, user_repo, user_session_factory):
        """同一 (scope, tag, language) への再設定は上書き (行は増えない)。"""
        user_repo.write_translation_preference("base", 10, "ja", "青い目")
        user_repo.write_translation_preference("base", 10, "ja", "青目")

        with user_session_factory() as session:
            rows = session.query(UserTagTranslationPreference).all()
            assert len(rows) == 1
            assert rows[0].translation == "青目"

    def test_languages_are_independent(self, user_repo, user_session_factory):
        user_repo.write_translation_preference("base", 10, "ja", "青い目")
        user_repo.write_translation_preference("base", 10, "en", "blue eyes")

        with user_session_factory() as session:
            assert session.query(UserTagTranslationPreference).count() == 2

    def test_delete_returns_true_then_false(self, user_repo):
        user_repo.write_translation_preference("base", 10, "ja", "青い目")

        assert user_repo.delete_translation_preference("base", 10, "ja") is True
        assert user_repo.delete_translation_preference("base", 10, "ja") is False


# --- OverlayTagReader: batch 取得 ---


class TestGetPreferredTranslationsBatch:
    def test_batch_returns_only_configured_tags(self, user_repo, overlay_reader):
        user_repo.write_translation_preference("base", 10, "ja", "青い目")
        user_repo.write_translation_preference("base", 20, "en", "flower")

        result = overlay_reader.get_preferred_translations_batch([10, 20, 30])

        assert result == {10: {"ja": "青い目"}, 20: {"en": "flower"}}

    def test_batch_empty_input(self, overlay_reader):
        assert overlay_reader.get_preferred_translations_batch([]) == {}

    def test_merged_reader_delegates_to_user_repo(self, user_repo, overlay_reader, user_session_factory):
        user_repo.write_translation_preference("base", 10, "ja", "青い目")
        merged = MergedTagReader(
            base_repo=TagReader(session_factory=user_session_factory),
            user_repo=overlay_reader,
        )

        assert merged.get_preferred_translations_batch([10]) == {10: {"ja": "青い目"}}

    def test_merged_reader_without_user_repo_returns_empty(self, user_session_factory):
        merged = MergedTagReader(base_repo=TagReader(session_factory=user_session_factory))

        assert merged.get_preferred_translations_batch([10]) == {}


# --- TagRepository: scope 解決つき公開経路 ---


class _FakeScopeReader:
    """get_tag_scope だけ実装した fake (write_user_translation と同じ契約)。"""

    def __init__(self, scopes: dict[int, str]) -> None:
        self._scopes = scopes

    def get_tag_scope(self, tag_id: int) -> str | None:
        return self._scopes.get(tag_id)


class TestTagRepositoryPreferredTranslation:
    def test_set_resolves_scope_via_reader(self, user_session_factory):
        repo = TagRepository(session_factory=user_session_factory, reader=_FakeScopeReader({10: "base"}))

        set_preferred_translation(repo, 10, "ja", "青い目")

        with user_session_factory() as session:
            row = session.query(UserTagTranslationPreference).one()
            assert (row.target_scope, row.target_tag_id) == ("base", 10)

    def test_set_rejects_unknown_tag_when_reader_present(self, user_session_factory):
        repo = TagRepository(session_factory=user_session_factory, reader=_FakeScopeReader({}))

        with pytest.raises(ValueError, match="set_preferred_translation"):
            set_preferred_translation(repo, 999, "ja", "青い目")

    def test_set_falls_back_to_offset_heuristic_without_reader(self, user_session_factory):
        repo = TagRepository(session_factory=user_session_factory)

        set_preferred_translation(repo, USER_TAG_ID_OFFSET + 1, "ja", "訳")

        with user_session_factory() as session:
            row = session.query(UserTagTranslationPreference).one()
            assert row.target_scope == "user"

    def test_clear_via_public_api(self, user_session_factory):
        repo = TagRepository(session_factory=user_session_factory, reader=_FakeScopeReader({10: "base"}))
        set_preferred_translation(repo, 10, "ja", "青い目")

        assert clear_preferred_translation(repo, 10, "ja") is True
        assert clear_preferred_translation(repo, 10, "ja") is False

    def test_get_via_public_api(self, user_repo, overlay_reader, user_session_factory):
        user_repo.write_translation_preference("base", 10, "ja", "青い目")
        merged = MergedTagReader(
            base_repo=TagReader(session_factory=user_session_factory),
            user_repo=overlay_reader,
        )

        assert get_preferred_translations_batch(merged, [10]) == {10: {"ja": "青い目"}}
