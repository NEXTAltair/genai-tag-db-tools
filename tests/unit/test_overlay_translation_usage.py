"""USER_TAG_TRANSLATION_PATCH / USER_TAG_USAGE_PATCH の単体テスト。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    UserOverlayBase,
    UserTagTranslationPatch,
    UserTagUsagePatch,
)
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository
from genai_tag_db_tools.models import TagRegisterRequest, TagTranslationInput
from genai_tag_db_tools.services.tag_register import TagRegisterService

# --- fixtures ---


@pytest.fixture()
def user_engine(tmp_path: Path):
    """tmp_path に Base + UserOverlayBase 両スキーマを持つ SQLite エンジン。"""
    db_path = tmp_path / "test_overlay_trans.sqlite"
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
    """テスト用 user DB セッションファクトリ。"""
    return sessionmaker(bind=user_engine, autoflush=False, autocommit=False)


@pytest.fixture()
def user_repo(user_session_factory):
    """テスト対象の UserTagRepository。"""
    return UserTagRepository(user_session_factory)


@pytest.fixture()
def overlay_reader(user_session_factory):
    """テスト対象の OverlayTagReader。"""
    return OverlayTagReader(session_factory=user_session_factory)


# --- TestUserTagTranslationPatch ---


class TestUserTagTranslationPatch:
    """write_translation_patch の INSERT・重複無視を検証する。"""

    def test_insert_new_translation(self, user_repo, user_session_factory):
        """新規翻訳が USER_TAG_TRANSLATION_PATCH に INSERT される。"""
        tag_id = USER_TAG_ID_OFFSET + 1
        user_repo.write_translation_patch("user", tag_id, "ja", "タグ")

        with user_session_factory() as session:
            rows = (
                session.query(UserTagTranslationPatch)
                .filter_by(target_scope="user", target_tag_id=tag_id)
                .all()
            )
        assert len(rows) == 1
        assert rows[0].language == "ja"
        assert rows[0].translation == "タグ"

    def test_duplicate_is_ignored(self, user_repo, user_session_factory):
        """同一 (scope, tag_id, language, translation) の重複は無視される。"""
        tag_id = USER_TAG_ID_OFFSET + 2
        user_repo.write_translation_patch("user", tag_id, "ja", "タグ")
        user_repo.write_translation_patch("user", tag_id, "ja", "タグ")

        with user_session_factory() as session:
            count = (
                session.query(UserTagTranslationPatch)
                .filter_by(target_scope="user", target_tag_id=tag_id)
                .count()
            )
        assert count == 1

    def test_different_language_creates_separate_row(self, user_repo, user_session_factory):
        """言語が異なれば別行になる。"""
        tag_id = USER_TAG_ID_OFFSET + 3
        user_repo.write_translation_patch("user", tag_id, "ja", "タグ")
        user_repo.write_translation_patch("user", tag_id, "zh", "标签")

        with user_session_factory() as session:
            rows = (
                session.query(UserTagTranslationPatch)
                .filter_by(target_scope="user", target_tag_id=tag_id)
                .all()
            )
        assert len(rows) == 2
        languages = {r.language for r in rows}
        assert languages == {"ja", "zh"}

    def test_different_translation_same_language_creates_separate_row(self, user_repo, user_session_factory):
        """同一言語でも翻訳文字列が異なれば別行になる（同義語として扱う）。"""
        tag_id = USER_TAG_ID_OFFSET + 4
        user_repo.write_translation_patch("user", tag_id, "ja", "タグA")
        user_repo.write_translation_patch("user", tag_id, "ja", "タグB")

        with user_session_factory() as session:
            count = (
                session.query(UserTagTranslationPatch)
                .filter_by(target_scope="user", target_tag_id=tag_id, language="ja")
                .count()
            )
        assert count == 2


# --- TestUserTagUsagePatch ---


class TestUserTagUsagePatch:
    """write_usage_patch の INSERT/UPDATE を検証する。"""

    def test_insert_new_usage(self, user_repo, user_session_factory):
        """新規 usage が USER_TAG_USAGE_PATCH に INSERT される。"""
        tag_id = USER_TAG_ID_OFFSET + 10
        user_repo.write_usage_patch("user", tag_id, 1000, 42)

        with user_session_factory() as session:
            row = (
                session.query(UserTagUsagePatch)
                .filter_by(target_scope="user", target_tag_id=tag_id, format_id=1000)
                .one_or_none()
            )
        assert row is not None
        assert row.count == 42

    def test_update_existing_usage(self, user_repo, user_session_factory):
        """同一 composite PK の行は count が UPDATE される。"""
        tag_id = USER_TAG_ID_OFFSET + 11
        user_repo.write_usage_patch("user", tag_id, 1000, 10)
        user_repo.write_usage_patch("user", tag_id, 1000, 99)

        with user_session_factory() as session:
            rows = (
                session.query(UserTagUsagePatch)
                .filter_by(target_scope="user", target_tag_id=tag_id, format_id=1000)
                .all()
            )
        assert len(rows) == 1
        assert rows[0].count == 99

    def test_different_format_creates_separate_row(self, user_repo, user_session_factory):
        """format_id が異なれば別行になる。"""
        tag_id = USER_TAG_ID_OFFSET + 12
        user_repo.write_usage_patch("user", tag_id, 1000, 5)
        user_repo.write_usage_patch("user", tag_id, 2000, 7)

        with user_session_factory() as session:
            count = (
                session.query(UserTagUsagePatch)
                .filter_by(target_scope="user", target_tag_id=tag_id)
                .count()
            )
        assert count == 2

    def test_get_usage_count_returns_count(self, user_repo, overlay_reader):
        """write_usage_patch で保存した count を get_usage_count で取得できる。"""
        tag_id = USER_TAG_ID_OFFSET + 13
        user_repo.write_usage_patch("user", tag_id, 1000, 77)

        result = overlay_reader.get_usage_count(tag_id, 1000)
        assert result == 77

    def test_get_usage_count_returns_base_scope_patch(self, user_repo, overlay_reader):
        user_repo.write_usage_patch("base", 100, 1000, 77)

        result = overlay_reader.get_usage_count(100, 1000)

        assert result == 77

    def test_get_usage_count_returns_none_when_absent(self, overlay_reader):
        """存在しないエントリは None を返す。"""
        assert overlay_reader.get_usage_count(USER_TAG_ID_OFFSET + 999, 1000) is None

    def test_list_usage_counts_all(self, user_repo, overlay_reader):
        """list_usage_counts() が全件を TagUsageCounts オブジェクトで返す。"""
        tag_id = USER_TAG_ID_OFFSET + 20
        user_repo.write_usage_patch("user", tag_id, 1000, 3)
        user_repo.write_usage_patch("user", tag_id, 2000, 8)

        results = overlay_reader.list_usage_counts(tag_id=tag_id)
        assert len(results) == 2
        counts_by_format = {r.format_id: r.count for r in results}
        assert counts_by_format[1000] == 3
        assert counts_by_format[2000] == 8

    def test_list_usage_counts_returns_base_scope_patch(self, user_repo, overlay_reader):
        user_repo.write_usage_patch("base", 100, 1000, 3)

        results = overlay_reader.list_usage_counts(tag_id=100)

        assert len(results) == 1
        assert results[0].tag_id == 100
        assert results[0].count == 3

    def test_list_usage_counts_filtered_by_format(self, user_repo, overlay_reader):
        """format_id 指定でフィルタリングされる。"""
        tag_id = USER_TAG_ID_OFFSET + 21
        user_repo.write_usage_patch("user", tag_id, 1000, 1)
        user_repo.write_usage_patch("user", tag_id, 2000, 2)

        results = overlay_reader.list_usage_counts(tag_id=tag_id, format_id=1000)
        assert len(results) == 1
        assert results[0].format_id == 1000


# --- TestOverlayReaderTranslations ---


class TestOverlayReaderTranslations:
    """USER_TAG_TRANSLATION_PATCH に書いたデータを OverlayTagReader で読めることを確認。"""

    def test_get_translations_returns_written_data(self, user_repo, overlay_reader):
        """write_translation_patch で保存した翻訳を get_translations で取得できる。"""
        tag_id = USER_TAG_ID_OFFSET + 100
        user_repo.write_translation_patch("user", tag_id, "ja", "犬")

        results = overlay_reader.get_translations(tag_id)
        assert len(results) == 1
        assert results[0].tag_id == tag_id
        assert results[0].language == "ja"
        assert results[0].translation == "犬"

    def test_get_translations_returns_base_scope_patch(self, user_repo, overlay_reader):
        user_repo.write_translation_patch("base", 100, "ja", "青い目")

        results = overlay_reader.get_translations(100)

        assert len(results) == 1
        assert results[0].tag_id == 100
        assert results[0].language == "ja"
        assert results[0].translation == "青い目"

    def test_get_translations_empty_for_unknown_tag(self, overlay_reader):
        """未登録 tag_id の場合は空リストを返す。"""
        assert overlay_reader.get_translations(USER_TAG_ID_OFFSET + 999) == []

    def test_get_translations_batch_returns_per_tag_dict(self, user_repo, overlay_reader):
        """get_translations_batch が tag_id → list[TagTranslation] の辞書を返す。"""
        tag_id_a = USER_TAG_ID_OFFSET + 101
        tag_id_b = USER_TAG_ID_OFFSET + 102
        user_repo.write_translation_patch("user", tag_id_a, "ja", "猫")
        user_repo.write_translation_patch("user", tag_id_b, "ja", "犬")

        result = overlay_reader.get_translations_batch([tag_id_a, tag_id_b])
        assert tag_id_a in result
        assert tag_id_b in result
        assert result[tag_id_a][0].translation == "猫"
        assert result[tag_id_b][0].translation == "犬"

    def test_get_translations_batch_returns_base_scope_patch(self, user_repo, overlay_reader):
        user_repo.write_translation_patch("base", 100, "ja", "猫")

        result = overlay_reader.get_translations_batch([100])

        assert result[100][0].translation == "猫"

    def test_get_translations_batch_empty_ids(self, overlay_reader):
        """空リストを渡した場合は空辞書を返す。"""
        assert overlay_reader.get_translations_batch([]) == {}

    def test_get_translations_batch_partial_miss(self, user_repo, overlay_reader):
        """一部が未登録でも登録済み分のみ返す。"""
        tag_id = USER_TAG_ID_OFFSET + 103
        user_repo.write_translation_patch("user", tag_id, "en", "cat")

        result = overlay_reader.get_translations_batch([tag_id, USER_TAG_ID_OFFSET + 9999])
        assert tag_id in result
        assert USER_TAG_ID_OFFSET + 9999 not in result


# --- TestRegisterUserTagWithTranslations ---


class _DummyRepo:
    """tag_register.py テスト用の最小 stub。"""

    def __init__(self) -> None:
        self._tag_ids: dict[str, int] = {}

    def get_format_id(self, format_name: str) -> int | None:
        return {"danbooru": 1}.get(format_name)

    def get_type_name_id(self, type_name: str) -> int | None:
        return {"unknown": 0, "general": 1}.get(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self._tag_ids.get(tag)

    def create_tag(self, source_tag: str, tag: str) -> int:
        tag_id = 10
        self._tag_ids[tag] = tag_id
        return tag_id

    def update_tag_status(self, tag_id, format_id, alias, preferred_tag_id, type_id=None):
        pass

    def add_or_update_translation(self, tag_id, language, translation):
        pass

    def create_type_name_if_not_exists(self, type_name, description=None):
        return {"unknown": 0, "general": 1}.get(type_name, 0)

    def create_format_if_not_exists(self, format_name, description=None, reader=None) -> int:
        return 1001

    def get_next_type_id(self, format_id: int) -> int:
        return 1

    def create_type_format_mapping_if_not_exists(self, format_id, type_id, type_name_id, description=None):
        return type_id


class _DummyReader:
    def __init__(self, repo: _DummyRepo) -> None:
        self._repo = repo

    def get_format_id(self, format_name: str) -> int:
        result = self._repo.get_format_id(format_name)
        if result is None:
            raise ValueError(f"Format not found: {format_name}")
        return result

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return self._repo.get_type_name_id(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self._repo.get_tag_id_by_name(tag, partial=partial)


class TestRegisterUserTagWithTranslations:
    """_register_user_tag が translations を write_translation_patch に渡すことを確認。"""

    def _make_service(self):
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        mock_user_repo.create_user_tag.return_value = USER_TAG_ID_OFFSET + 1
        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        return service, mock_user_repo

    def test_translations_written_to_patch(self):
        """translations が指定されると write_translation_patch が翻訳ごとに呼ばれる。"""
        service, mock_user_repo = self._make_service()
        request = TagRegisterRequest(
            tag="neko",
            format_name="danbooru",
            type_name="general",
            scope="user",
            translations=[
                TagTranslationInput(language="ja", translation="猫"),
                TagTranslationInput(language="zh", translation="猫咪"),
            ],
        )

        result = service.register_tag(request)

        assert mock_user_repo.write_translation_patch.call_count == 2
        calls = mock_user_repo.write_translation_patch.call_args_list
        first_kwargs = calls[0].kwargs
        assert first_kwargs["target_scope"] == "user"
        assert first_kwargs["target_tag_id"] == USER_TAG_ID_OFFSET + 1
        assert first_kwargs["language"] == "ja"
        assert first_kwargs["translation"] == "猫"
        assert result.tag_id == USER_TAG_ID_OFFSET + 1

    def test_no_translations_write_patch_not_called(self):
        """translations が None の場合は write_translation_patch が呼ばれない。"""
        service, mock_user_repo = self._make_service()
        request = TagRegisterRequest(
            tag="inu",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        service.register_tag(request)

        mock_user_repo.write_translation_patch.assert_not_called()

    def test_empty_translations_write_patch_not_called(self):
        """translations が空リストの場合も write_translation_patch が呼ばれない。"""
        service, mock_user_repo = self._make_service()
        request = TagRegisterRequest(
            tag="tori",
            format_name="danbooru",
            type_name="general",
            scope="user",
            translations=[],
        )

        service.register_tag(request)

        mock_user_repo.write_translation_patch.assert_not_called()

    def test_write_patch_still_called_with_translations(self):
        """translations の有無に関わらず write_patch は必ず呼ばれる。"""
        service, mock_user_repo = self._make_service()
        request = TagRegisterRequest(
            tag="sakana",
            format_name="danbooru",
            type_name="general",
            scope="user",
            translations=[TagTranslationInput(language="ja", translation="魚")],
        )

        service.register_tag(request)

        mock_user_repo.write_patch.assert_called_once()
        mock_user_repo.write_translation_patch.assert_called_once()
