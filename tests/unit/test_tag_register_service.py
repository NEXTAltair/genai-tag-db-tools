import pytest

from genai_tag_db_tools.models import TagRegisterRequest, TagTranslationInput
from genai_tag_db_tools.services.tag_register import TagRegisterService


class DummyRepo:
    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.status_updates: list[tuple[int, int, bool, int, int | None]] = []
        self.translations: list[tuple[int, str, str]] = []
        self.usage_updates: list[tuple[int, int, int]] = []
        self._tag_ids: dict[str, int] = {}
        self.format_creations: list[str] = []
        self.mapping_creations: list[tuple[int, int, int]] = []

    def get_format_id(self, format_name: str) -> int | None:
        return {"danbooru": 1}.get(format_name)

    def get_type_name_id(self, type_name: str) -> int | None:
        return {"character": 2, "general": 1}.get(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        if tag == "preferred":
            return 99
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
        self.translations.append((tag_id, language, translation))

    def update_usage_count(self, tag_id: int, format_id: int, count: int) -> None:
        self.usage_updates.append((tag_id, format_id, count))

    def create_type_name_if_not_exists(self, type_name: str, description: str | None = None) -> int:
        return {"unknown": 0, "character": 2, "general": 1}.get(type_name, 0)

    def create_format_if_not_exists(
        self,
        format_name: str,
        description: str | None = None,
        reader: object = None,
    ) -> int:
        """フォーマット自動作成スタブ。"""
        self.format_creations.append(format_name)
        self._auto_format_id = getattr(self, "_auto_format_id", 1000) + 1
        return self._auto_format_id

    def get_next_type_id(self, format_id: int) -> int:
        return 1

    def create_type_format_mapping_if_not_exists(
        self, format_id: int, type_id: int, type_name_id: int, description: str | None = None
    ) -> int:
        self.mapping_creations.append((format_id, type_id, type_name_id))
        return type_id


class DummyReader:
    def __init__(self, repo: DummyRepo) -> None:
        self.repo = repo

    def get_format_id(self, format_name: str) -> int:
        result = self.repo.get_format_id(format_name)
        if result is None:
            raise ValueError(f"Format not found: {format_name}")
        return result

    def get_type_name_id(self, type_name: str) -> int | None:
        return self.repo.get_type_name_id(type_name)

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        """format固有のtype_idを返す。DummyRepoのtype_name_idをそのまま使用。"""
        return self.repo.get_type_name_id(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self.repo.get_tag_id_by_name(tag, partial=partial)


@pytest.mark.db_tools
def test_register_tag_creates_and_updates_status():
    repo = DummyRepo()
    reader = DummyReader(repo)
    service = TagRegisterService(repository=repo, reader=reader)
    request = TagRegisterRequest(
        tag="foo",
        source_tag=None,
        format_name="danbooru",
        type_name="character",
        translations=[TagTranslationInput(language="ja", translation="フー")],
    )

    result = service.register_tag(request)

    assert result.created is True
    assert repo.created_tags == [("foo", "foo")]
    assert repo.status_updates == [(10, 1, False, 10, 2)]
    assert repo.translations == [(10, "ja", "フー")]


@pytest.mark.db_tools
def test_register_tag_alias_requires_preferred():
    repo = DummyRepo()
    reader = DummyReader(repo)
    service = TagRegisterService(repository=repo, reader=reader)
    request = TagRegisterRequest(
        tag="foo",
        source_tag=None,
        format_name="danbooru",
        type_name="character",
        alias=True,
    )

    with pytest.raises(ValueError, match="preferred_tag"):
        service.register_tag(request)


@pytest.mark.db_tools
def test_register_tag_alias_resolves_preferred():
    repo = DummyRepo()
    reader = DummyReader(repo)
    service = TagRegisterService(repository=repo, reader=reader)
    request = TagRegisterRequest(
        tag="foo",
        source_tag=None,
        format_name="danbooru",
        type_name="character",
        alias=True,
        preferred_tag="preferred",
    )

    result = service.register_tag(request)

    assert result.created is True
    assert repo.status_updates == [(10, 1, True, 99, 2)]


@pytest.mark.db_tools
def test_register_or_update_tag_routes_to_register_tag():
    repo = DummyRepo()
    reader = DummyReader(repo)
    service = TagRegisterService(repository=repo, reader=reader)

    request = TagRegisterRequest(
        tag="foo",
        source_tag="foo",
        format_name="danbooru",
        type_name="general",
    )

    result = service.register_tag(request)

    assert result.tag_id == 10
    assert result.created is True


# ==============================================================================
# Test _resolve_format_id
# ==============================================================================


class TestResolveFormatId:
    """_resolve_format_idの単体テスト。"""

    @pytest.mark.db_tools
    def test_resolve_existing_format(self):
        """既存フォーマット名はそのままformat_idを返す。"""
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)

        fmt_id = service._resolve_format_id("danbooru")

        assert fmt_id == 1

    @pytest.mark.db_tools
    def test_resolve_unknown_format_auto_creates(self):
        """未知のフォーマット名は自動作成される。"""
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)

        fmt_id = service._resolve_format_id("new_format")

        # DummyRepoのcreate_format_if_not_existsが返すID
        assert isinstance(fmt_id, int)
        assert fmt_id > 0
        # 呼び出しが記録されていることを検証
        assert repo.format_creations == ["new_format"]


# ==============================================================================
# Test _resolve_type_id
# ==============================================================================


class TestResolveTypeId:
    """_resolve_type_idの単体テスト。"""

    @pytest.mark.db_tools
    def test_resolve_existing_type(self):
        """既存タイプ名は対応するtype_idを返す。"""
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)

        type_id = service._resolve_type_id("character", "danbooru", 1)

        assert type_id == 2

    @pytest.mark.db_tools
    def test_resolve_nonexistent_type_creates_new_mapping(self):
        """未知のタイプ名は新規type_idで自動作成される（unknown以外は0を使わない）。"""
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)

        type_id = service._resolve_type_id("nonexistent_type", "danbooru", 1)

        # DummyRepoのget_next_type_idが1を返すので、type_id=1で作成
        assert type_id == 1

    @pytest.mark.db_tools
    def test_resolve_type_existing_returns_directly(self):
        """既存タイプはformat固有のtype_idをそのまま返す。"""
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)

        # generalは既存(type_id=1)
        type_id = service._resolve_type_id("general", "danbooru", 1)

        assert type_id == 1
        # 既存のためマッピング作成は呼ばれない
        assert repo.mapping_creations == []

    @pytest.mark.db_tools
    def test_resolve_type_unknown_creates_type_name(self):
        """未知タイプではcreate_type_name_if_not_existsが呼ばれる。"""
        from unittest.mock import Mock

        repo = Mock()
        reader = Mock()
        # type_name_idは取得できるがformat固有のtype_idは未存在
        reader.get_type_id_for_format.return_value = None
        repo.create_type_name_if_not_exists.return_value = 50
        repo.get_next_type_id.return_value = 1
        repo.create_type_format_mapping_if_not_exists.return_value = 1

        service = TagRegisterService(repository=repo, reader=reader)

        # unknown以外のタイプはget_next_type_idで採番
        type_id = service._resolve_type_id("brand_new_type", "danbooru", 1)

        assert type_id == 1
        repo.create_type_name_if_not_exists.assert_called_once_with(
            type_name="brand_new_type",
            description="Auto-created type: brand_new_type",
        )
        repo.create_type_format_mapping_if_not_exists.assert_called_once_with(
            format_id=1,
            type_id=1,
            type_name_id=50,
            description="Auto-created mapping for danbooru/brand_new_type",
        )

    @pytest.mark.db_tools
    def test_resolve_type_returns_repository_resolved_type_id(self):
        """競合時はrepoが返した最終type_idを返す。"""
        from unittest.mock import Mock

        repo = Mock()
        reader = Mock()
        reader.get_type_id_for_format.return_value = None
        repo.create_type_name_if_not_exists.return_value = 50
        repo.get_next_type_id.return_value = 1
        # 競合等でrepo側が異なるtype_idを返したケース
        repo.create_type_format_mapping_if_not_exists.return_value = 5

        service = TagRegisterService(repository=repo, reader=reader)

        type_id = service._resolve_type_id("brand_new_type", "danbooru", 1)

        assert type_id == 5

    @pytest.mark.db_tools
    def test_resolve_type_unknown_uses_zero(self):
        """unknownタイプはtype_id=0で作成される。"""
        from unittest.mock import Mock

        repo = Mock()
        reader = Mock()
        reader.get_type_id_for_format.return_value = None
        repo.create_type_name_if_not_exists.return_value = 50
        repo.create_type_format_mapping_if_not_exists.return_value = 0

        service = TagRegisterService(repository=repo, reader=reader)

        type_id = service._resolve_type_id("unknown", "danbooru", 1)

        assert type_id == 0
        repo.create_type_format_mapping_if_not_exists.assert_called_once_with(
            format_id=1,
            type_id=0,
            type_name_id=50,
            description="Auto-created mapping for danbooru/unknown",
        )

    @pytest.mark.db_tools
    def test_resolve_type_existing_returns_type_id(self):
        """既存タイプはformat固有のtype_idをそのまま返す。"""
        from unittest.mock import Mock

        repo = Mock()
        reader = Mock()
        reader.get_type_id_for_format.return_value = 5  # 既存type_id
        repo.create_type_name_if_not_exists.return_value = 30

        service = TagRegisterService(repository=repo, reader=reader)

        type_id = service._resolve_type_id("existing_type", "danbooru", 1)

        assert type_id == 5
        # マッピングが既存なので create は呼ばれない
        repo.create_type_format_mapping_if_not_exists.assert_not_called()


# ==============================================================================
# Test type_id/type_name inconsistency detection
# ==============================================================================


class TestTypeInconsistencyDetection:
    """type_idとtype_nameの不整合検知テスト。"""

    @pytest.mark.db_tools
    def test_unknown_name_with_nonzero_type_id_warns(self, caplog):
        """type_name='unknown'なのにtype_id!=0の場合warningが出る。"""
        import logging
        from unittest.mock import Mock

        repo = Mock()
        reader = Mock()
        # "unknown"に対してformat固有type_id=5が返る(不整合)
        reader.get_type_id_for_format.return_value = 5
        repo.create_type_name_if_not_exists.return_value = 0

        service = TagRegisterService(repository=repo, reader=reader)

        with caplog.at_level(logging.WARNING):
            type_id = service._resolve_type_id("unknown", "danbooru", 1)

        assert type_id == 5
        assert any("type_id/type_name mismatch" in msg for msg in caplog.messages)
        assert any("type_name='unknown' but type_id=5" in msg for msg in caplog.messages)

    @pytest.mark.db_tools
    def test_named_type_with_zero_type_id_warns(self, caplog):
        """名前付きタイプがtype_id=0に解決された場合warningが出る。"""
        import logging
        from unittest.mock import Mock

        repo = Mock()
        reader = Mock()
        # "character"に対してformat固有type_id=0が返る(不整合)
        reader.get_type_id_for_format.return_value = 0
        repo.create_type_name_if_not_exists.return_value = 2

        service = TagRegisterService(repository=repo, reader=reader)

        with caplog.at_level(logging.WARNING):
            type_id = service._resolve_type_id("character", "danbooru", 1)

        assert type_id == 0
        assert any("type_id/type_name mismatch" in msg for msg in caplog.messages)
        assert any("type_name='character' resolved to type_id=0" in msg for msg in caplog.messages)
