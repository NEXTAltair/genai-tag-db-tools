"""UserTagRepository および TagRegisterService の overlay scope テスト。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.runtime import _create_engine
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    LocalFeedbackApplication,
    TagFormat,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTagStatusPatch,
)
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository
from genai_tag_db_tools.models import TagRegisterRequest
from genai_tag_db_tools.services.tag_register import TagRegisterService

# --- fixtures ---


@pytest.fixture()
def user_engine(tmp_path: Path):
    """tmp_path に Base + UserOverlayBase 両スキーマを持つ SQLite エンジン。"""
    db_path = tmp_path / "user_test.sqlite"
    engine = _create_engine(db_path)
    Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def user_session_factory(user_engine):
    """user DB セッションファクトリ。"""
    return sessionmaker(bind=user_engine, autoflush=False, autocommit=False)


@pytest.fixture()
def user_repo(user_session_factory):
    return UserTagRepository(user_session_factory)


# --- TestCreateUserTag ---


class TestCreateUserTag:
    def test_create_new_tag(self, user_repo):
        """正常作成: 新しいタグが USER_TAGS に登録される。"""
        tag_id = user_repo.create_user_tag("my_src", "my_tag")
        assert tag_id >= USER_TAG_ID_OFFSET

    def test_create_returns_offset_for_first_tag(self, user_repo):
        """初回登録は USER_TAG_ID_OFFSET そのもの。"""
        tag_id = user_repo.create_user_tag("src", "first_tag")
        assert tag_id == USER_TAG_ID_OFFSET

    def test_create_duplicate_returns_existing_id(self, user_repo):
        """同一 tag 文字列を登録すると既存 tag_id を返す。"""
        id1 = user_repo.create_user_tag("src", "dup_tag")
        id2 = user_repo.create_user_tag("src2", "dup_tag")
        assert id1 == id2

    def test_tag_id_always_gte_offset(self, user_repo):
        """複数タグ登録後も tag_id >= USER_TAG_ID_OFFSET を保証。"""
        for i in range(5):
            tid = user_repo.create_user_tag(f"src{i}", f"tag_{i}")
            assert tid >= USER_TAG_ID_OFFSET

    def test_sequential_ids_increment(self, user_repo):
        """連続登録で tag_id が単調増加する。"""
        id1 = user_repo.create_user_tag("s1", "tag_a")
        id2 = user_repo.create_user_tag("s2", "tag_b")
        assert id2 > id1


# --- TestWritePatch ---


class TestWritePatch:
    def _make_patch_kwargs(self, **overrides) -> dict:
        base: dict = {
            "target_scope": "user",
            "target_tag_id": USER_TAG_ID_OFFSET + 1,
            "format_id": 1000,
            "type_id": 0,
            "alias": False,
            "preferred_scope": "user",
            "preferred_tag_id": USER_TAG_ID_OFFSET + 1,
            "deprecated": False,
        }
        base.update(overrides)
        return base

    def test_insert_new_patch(self, user_repo, user_session_factory):
        """新規パッチが INSERT される。"""
        user_repo.write_patch(**self._make_patch_kwargs())
        with user_session_factory() as session:
            row = (
                session.query(UserTagStatusPatch)
                .filter_by(
                    target_scope="user",
                    target_tag_id=USER_TAG_ID_OFFSET + 1,
                    format_id=1000,
                )
                .one_or_none()
            )
        assert row is not None
        assert row.alias is False

    def test_update_existing_patch(self, user_repo, user_session_factory):
        """既存行 (同一 composite PK) は UPDATE される。"""
        user_repo.write_patch(**self._make_patch_kwargs())
        # alias=True に更新 (preferred は別タグ)
        updated_kwargs = self._make_patch_kwargs(
            alias=True,
            preferred_scope="base",
            preferred_tag_id=100,
        )
        user_repo.write_patch(**updated_kwargs)
        with user_session_factory() as session:
            rows = (
                session.query(UserTagStatusPatch)
                .filter_by(
                    target_scope="user",
                    target_tag_id=USER_TAG_ID_OFFSET + 1,
                    format_id=1000,
                )
                .all()
            )
        assert len(rows) == 1
        assert rows[0].alias is True
        assert rows[0].preferred_scope == "base"

    def test_composite_pk_uniqueness(self, user_repo, user_session_factory):
        """異なる format_id は別行になる。"""
        user_repo.write_patch(**self._make_patch_kwargs(format_id=1000))
        user_repo.write_patch(**self._make_patch_kwargs(format_id=2000))
        with user_session_factory() as session:
            count = session.query(UserTagStatusPatch).count()
        assert count == 2

    def test_cross_scope_alias_patch(self, user_repo):
        """user tag が base tag を preferred に持つクロススコープ alias が書ける。"""
        user_repo.write_patch(
            target_scope="user",
            target_tag_id=USER_TAG_ID_OFFSET + 1,
            format_id=1000,
            type_id=0,
            alias=True,
            preferred_scope="base",
            preferred_tag_id=100,
        )


class TestLocalFeedbackRepositoryHelpers:
    def test_get_or_create_format_id_uses_user_offset_sequence(self, user_repo, user_session_factory):
        format_id = user_repo.get_or_create_format_id("danbooru")

        assert format_id == 1000
        assert user_repo.get_format_id("danbooru") == 1000
        with user_session_factory() as session:
            row = session.query(TagFormat).filter_by(format_name="danbooru").one()
        assert row.format_id == 1000

    def test_get_or_create_format_id_reuses_reader_resolved_id(self, user_repo):
        format_id = user_repo.get_or_create_format_id("danbooru", format_id=1)

        assert format_id == 1
        assert user_repo.get_or_create_format_id("danbooru", format_id=1) == 1

    def test_get_or_create_type_id_creates_type_name_and_mapping(self, user_repo, user_session_factory):
        user_repo.get_or_create_format_id("danbooru", format_id=1000)

        type_id = user_repo.get_or_create_type_id(1000, "general")

        assert type_id == 1
        assert user_repo.get_type_id(1000, "general") == 1
        assert user_repo.get_type_name_for_type_id(1000, 1) == "general"
        with user_session_factory() as session:
            assert session.query(TagTypeName).filter_by(type_name="general").count() == 1
            assert session.query(TagTypeFormatMapping).filter_by(format_id=1000, type_id=1).count() == 1

    def test_get_or_create_type_id_preserves_unknown_as_zero(self, user_repo):
        user_repo.get_or_create_format_id("danbooru", format_id=1000)

        assert user_repo.get_or_create_type_id(1000, "unknown") == 0
        assert user_repo.get_type_name_for_type_id(1000, 0) == "unknown"

    def test_get_or_create_type_id_rejects_unknown_when_zero_is_owned(self, user_repo):
        user_repo.get_or_create_format_id("danbooru", format_id=1000)
        assert user_repo.get_or_create_type_id(1000, "general", type_id=0) == 0

        with pytest.raises(ValueError, match=r"type_id=0.*'general'"):
            user_repo.get_or_create_type_id(1000, "unknown")

    def test_has_applied_feedback_allows_legacy_duplicate_applied_rows(
        self,
        user_repo,
        user_session_factory,
    ):
        approved_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
        with user_session_factory() as session:
            session.execute(text("DROP INDEX IF EXISTS uix_local_feedback_applied_hash"))
            session.commit()

        for _ in range(2):
            user_repo.record_feedback_application(
                proposal_hash="duplicate",
                proposal_kind="translation_correction",
                target_kind="translation",
                target_scope="base",
                target_tag_id=10,
                format_name=None,
                field="translation.ja",
                approved_by="tester",
                approved_at=approved_at,
                status="applied",
                dry_run=False,
                proposal_json="{}",
                before_json=None,
                after_json='{"changes":[]}',
            )

        assert user_repo.has_applied_feedback("duplicate") is True

    def test_get_status_patch_returns_detached_copy(self, user_repo):
        user_repo.write_patch(
            target_scope="base",
            target_tag_id=10,
            format_id=1,
            type_id=5,
            alias=True,
            preferred_scope="base",
            preferred_tag_id=99,
            deprecated=True,
        )

        row = user_repo.get_status_patch("base", 10, 1)

        assert row is not None
        assert row.target_scope == "base"
        assert row.type_id == 5
        assert row.alias is True
        assert row.preferred_tag_id == 99
        assert row.deprecated is True

    def test_record_and_list_feedback_applications(self, user_repo):
        approved_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)

        row = user_repo.record_feedback_application(
            proposal_hash="abc123",
            proposal_kind="translation_correction",
            target_kind="translation",
            target_scope="base",
            target_tag_id=10,
            format_name=None,
            field="translation.ja",
            approved_by="tester",
            approved_at=approved_at,
            status="applied",
            dry_run=False,
            proposal_json="{}",
            before_json=None,
            after_json='{"changes":[]}',
        )

        assert row.application_id == 1
        assert user_repo.has_applied_feedback("abc123") is True
        records = user_repo.list_feedback_applications()
        assert len(records) == 1
        assert isinstance(records[0], LocalFeedbackApplication)
        assert records[0].proposal_hash == "abc123"


# --- DummyRepo / DummyReader (既存テストパターンに準拠) ---


class _DummyRepo:
    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.status_updates: list[tuple] = []
        self._tag_ids: dict[str, int] = {}
        self.format_creations: list[str] = []
        self.mapping_creations: list[tuple] = []

    def get_format_id(self, format_name: str) -> int | None:
        return {"danbooru": 1}.get(format_name)

    def get_type_name_id(self, type_name: str) -> int | None:
        return {"unknown": 0, "general": 1, "character": 2}.get(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self._tag_ids.get(tag)

    def create_tag(self, source_tag: str, tag: str) -> int:
        self.created_tags.append((source_tag, tag))
        tag_id = 10
        self._tag_ids[tag] = tag_id
        return tag_id

    def update_tag_status(
        self,
        tag_id: int,
        format_id: int,
        alias: bool,
        preferred_tag_id: int,
        type_id: int | None = None,
    ) -> None:
        self.status_updates.append((tag_id, format_id, alias, preferred_tag_id, type_id))

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        pass

    def create_type_name_if_not_exists(self, type_name: str, description: str | None = None) -> int:
        return {"unknown": 0, "general": 1, "character": 2}.get(type_name, 0)

    def create_format_if_not_exists(
        self,
        format_name: str,
        description: str | None = None,
        reader: object = None,
    ) -> int:
        self.format_creations.append(format_name)
        self._auto_format_id = getattr(self, "_auto_format_id", 1000) + 1
        return self._auto_format_id

    def get_next_type_id(self, format_id: int) -> int:
        return 1

    def create_type_format_mapping_if_not_exists(
        self,
        format_id: int,
        type_id: int,
        type_name_id: int,
        description: str | None = None,
    ) -> int:
        self.mapping_creations.append((format_id, type_id, type_name_id))
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


# --- TestTagRegisterServiceUserScope ---


class TestTagRegisterServiceUserScope:
    """scope="user" のとき overlay path が使われることを確認。"""

    def test_register_user_tag_calls_create_and_write_patch(self):
        """create_user_tag と write_patch が呼ばれる。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        mock_user_repo.create_user_tag.return_value = USER_TAG_ID_OFFSET + 1

        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        request = TagRegisterRequest(
            tag="user_tag",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        result = service.register_tag(request)

        mock_user_repo.create_user_tag.assert_called_once()
        mock_user_repo.write_patch.assert_called_once()
        assert result.tag_id == USER_TAG_ID_OFFSET + 1

    def test_register_user_tag_without_user_db_raises(self):
        """user_tag_repo=None のとき RuntimeError が発生する。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=None)
        request = TagRegisterRequest(
            tag="user_tag",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )
        with pytest.raises(RuntimeError, match="User DB"):
            service.register_tag(request)

    def test_register_user_alias_resolves_preferred_base_scope(self):
        """alias=True で preferred が base タグのとき preferred_scope="base" になる。"""
        repo = _DummyRepo()
        repo._tag_ids["preferred_tag"] = 500  # base DB のタグ (OFFSET 未満)
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        mock_user_repo.create_user_tag.return_value = USER_TAG_ID_OFFSET + 1

        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        request = TagRegisterRequest(
            tag="alias_tag",
            format_name="danbooru",
            type_name="general",
            alias=True,
            preferred_tag="preferred_tag",
            scope="user",
        )

        service.register_tag(request)

        call_kwargs = mock_user_repo.write_patch.call_args.kwargs
        assert call_kwargs["alias"] is True
        assert call_kwargs["preferred_tag_id"] == 500
        assert call_kwargs["preferred_scope"] == "base"

    def test_register_user_non_alias_uses_self_as_preferred(self):
        """alias=False のとき preferred_scope="user" かつ preferred_tag_id=tag_id。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        new_tag_id = USER_TAG_ID_OFFSET + 10
        mock_user_repo.create_user_tag.return_value = new_tag_id

        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        request = TagRegisterRequest(
            tag="solo_tag",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        service.register_tag(request)

        call_kwargs = mock_user_repo.write_patch.call_args.kwargs
        assert call_kwargs["alias"] is False
        assert call_kwargs["preferred_scope"] == "user"
        assert call_kwargs["preferred_tag_id"] == new_tag_id
        assert call_kwargs["target_scope"] == "user"

    def test_register_user_tag_result_created_true_for_new_tag(self):
        """存在しないタグは created=True を返す。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        mock_user_repo.create_user_tag.return_value = USER_TAG_ID_OFFSET + 1

        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        request = TagRegisterRequest(
            tag="brand_new",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        result = service.register_tag(request)
        assert result.created is True

    def test_register_user_tag_result_created_false_for_existing_tag(self):
        """既存タグ (reader で見つかる) は created=False を返す。"""
        repo = _DummyRepo()
        repo._tag_ids["existing_tag"] = USER_TAG_ID_OFFSET + 5
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        mock_user_repo.create_user_tag.return_value = USER_TAG_ID_OFFSET + 5

        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        request = TagRegisterRequest(
            tag="existing_tag",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        result = service.register_tag(request)
        assert result.created is False


# --- TestTagRegisterServiceBaseScope ---


class TestTagRegisterServiceBaseScope:
    """scope="base" (既定) のとき既存パスが使われることを確認。"""

    def test_base_scope_uses_create_tag_on_base_repo(self):
        """scope="base" は TAGS テーブルへの create_tag を呼ぶ。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)
        request = TagRegisterRequest(
            tag="base_tag",
            format_name="danbooru",
            type_name="general",
            scope="base",
        )

        result = service.register_tag(request)

        assert repo.created_tags == [("base_tag", "base_tag")]
        assert len(repo.status_updates) == 1
        assert result.tag_id == 10

    def test_default_scope_is_base(self):
        """scope を省略すると "base" として動作する。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)
        request = TagRegisterRequest(
            tag="default_tag",
            format_name="danbooru",
            type_name="general",
        )

        result = service.register_tag(request)

        assert repo.created_tags == [("default_tag", "default_tag")]
        assert len(repo.status_updates) == 1
        assert result.tag_id == 10

    def test_base_scope_does_not_call_user_tag_repo(self):
        """scope="base" のとき user_tag_repo メソッドは呼ばれない。"""
        repo = _DummyRepo()
        reader = _DummyReader(repo)
        mock_user_repo = MagicMock()
        service = TagRegisterService(repository=repo, reader=reader, user_tag_repo=mock_user_repo)
        request = TagRegisterRequest(
            tag="base_tag",
            format_name="danbooru",
            type_name="general",
            scope="base",
        )

        service.register_tag(request)

        mock_user_repo.create_user_tag.assert_not_called()
        mock_user_repo.write_patch.assert_not_called()
