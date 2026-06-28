import pytest

from genai_tag_db_tools.db.schema import USER_TAG_ID_OFFSET
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


# ==============================================================================
# Dummies for scope="user" registration (Issue #78 / #62)
# ==============================================================================


class DummyUserTagRepo:
    """USER_TAGS / patch 書き込みを記録するスタブ。"""

    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.patches: list[dict] = []
        self.translation_patches: list[dict] = []
        self._tags: dict[str, int] = {}
        self._next_id = USER_TAG_ID_OFFSET

    def create_user_tag(self, source_tag: str, tag: str) -> int:
        missing = [name for name, value in (("tag", tag), ("source_tag", source_tag)) if not value]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        if tag in self._tags:
            return self._tags[tag]
        tag_id = self._next_id
        self._next_id += 1
        self._tags[tag] = tag_id
        self.created_tags.append((source_tag, tag))
        return tag_id

    def write_patch(self, **kwargs) -> None:
        self.patches.append(kwargs)

    def write_translation_patch(self, **kwargs) -> None:
        self.translation_patches.append(kwargs)


class DummyUserReader:
    """user scope 登録用の reader スタブ。

    name_to_id / id_to_scope を差し替えて preferred 解決と scope 判定を制御する。
    """

    def __init__(
        self,
        name_to_id: dict[str, int] | None = None,
        id_to_scope: dict[int, str] | None = None,
    ) -> None:
        self.name_to_id = name_to_id or {}
        self.id_to_scope = id_to_scope or {}

    def get_format_id(self, format_name: str) -> int:
        result = {"danbooru": 1}.get(format_name)
        if result is None:
            raise ValueError(f"Format not found: {format_name}")
        return result

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return {"character": 2, "general": 1}.get(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self.name_to_id.get(tag)

    def get_tag_scope(self, tag_id: int) -> str | None:
        return self.id_to_scope.get(tag_id)


def _make_user_service(reader: DummyUserReader) -> tuple[TagRegisterService, DummyUserTagRepo]:
    base_repo = DummyRepo()
    user_repo = DummyUserTagRepo()
    service = TagRegisterService(repository=base_repo, reader=reader, user_tag_repo=user_repo)
    return service, user_repo


# ==============================================================================
# Issue #62 / #78-4: 正規化後に空になるタグの拒否
# ==============================================================================


class TestRejectEmptyNormalizedTag:
    """空文字・空白のみ・正規化後空のタグ登録を拒否する。"""

    @pytest.mark.db_tools
    @pytest.mark.parametrize("bad_tag", ["", "   ", "___"])
    def test_base_scope_rejects_empty_normalized(self, bad_tag):
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = TagRegisterService(repository=repo, reader=reader)
        request = TagRegisterRequest(
            tag=bad_tag,
            source_tag="weird_source",
            format_name="danbooru",
            type_name="general",
        )

        with pytest.raises(ValueError, match="正規化後のタグが空"):
            service.register_tag(request)

        # 空の tag row は作られない
        assert repo.created_tags == []

    @pytest.mark.db_tools
    @pytest.mark.parametrize("bad_tag", ["", "   ", "___"])
    def test_user_scope_rejects_empty_normalized(self, bad_tag):
        reader = DummyUserReader()
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag=bad_tag,
            source_tag="weird_source",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        with pytest.raises(ValueError, match="正規化後のタグが空"):
            service.register_tag(request)

        assert user_repo.created_tags == []
        assert user_repo.patches == []

    @pytest.mark.db_tools
    def test_normalizable_tag_is_accepted(self):
        """blue__eyes は blue eyes に正規化できるため登録可能。"""
        reader = DummyUserReader()
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag="blue__eyes",
            source_tag="blue__eyes",
            format_name="danbooru",
            type_name="general",
            scope="user",
        )

        result = service.register_tag(request)

        assert result.created is True
        assert user_repo.created_tags == [("blue__eyes", "blue__eyes")]


# ==============================================================================
# Issue #78-1: alias preferred 解決失敗時に user タグを作らない
# ==============================================================================


class TestUserAliasPreValidation:
    @pytest.mark.db_tools
    def test_missing_preferred_does_not_create_user_tag(self):
        # preferred は解決できない (name_to_id 空)
        reader = DummyUserReader()
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag="alias_tag",
            source_tag="alias_tag",
            format_name="danbooru",
            type_name="general",
            alias=True,
            preferred_tag="does_not_exist",
            scope="user",
        )

        with pytest.raises(ValueError, match="推奨タグが見つかりません"):
            service.register_tag(request)

        # USER_TAGS 行も status patch も残らない (中途半端な状態を作らない)
        assert user_repo.created_tags == []
        assert user_repo.patches == []


# ==============================================================================
# Issue #78-3: preferred_scope を reader 経由で判定 (数値 offset 非依存)
# ==============================================================================


class TestPreferredScopeResolution:
    @pytest.mark.db_tools
    def test_low_id_user_tag_resolves_to_user_scope(self):
        """offset 未満の ID でも reader が user と返せば preferred_scope=user。"""
        # 旧 TAGS パスで登録された user DB タグ (offset 未満の ID) を模す
        legacy_user_id = 500
        reader = DummyUserReader(
            name_to_id={"legacy_preferred": legacy_user_id},
            id_to_scope={legacy_user_id: "user"},
        )
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag="alias_tag",
            source_tag="alias_tag",
            format_name="danbooru",
            type_name="general",
            alias=True,
            preferred_tag="legacy_preferred",
            scope="user",
        )

        result = service.register_tag(request)

        assert result.created is True
        assert len(user_repo.patches) == 1
        patch = user_repo.patches[0]
        # 数値 offset なら "base" になるが reader 判定で "user" になる
        assert patch["preferred_scope"] == "user"
        assert patch["preferred_tag_id"] == legacy_user_id

    @pytest.mark.db_tools
    def test_base_preferred_resolves_to_base_scope(self):
        base_id = 100
        reader = DummyUserReader(
            name_to_id={"base_preferred": base_id},
            id_to_scope={base_id: "base"},
        )
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag="alias_tag",
            source_tag="alias_tag",
            format_name="danbooru",
            type_name="general",
            alias=True,
            preferred_tag="base_preferred",
            scope="user",
        )

        service.register_tag(request)

        assert user_repo.patches[0]["preferred_scope"] == "base"

    @pytest.mark.db_tools
    def test_scope_falls_back_to_numeric_offset_when_reader_silent(self):
        """reader が scope を返せない場合は数値 offset にフォールバックする。"""
        high_id = USER_TAG_ID_OFFSET + 5
        reader = DummyUserReader(
            name_to_id={"pref": high_id},
            id_to_scope={},  # get_tag_scope -> None
        )
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag="alias_tag",
            source_tag="alias_tag",
            format_name="danbooru",
            type_name="general",
            alias=True,
            preferred_tag="pref",
            scope="user",
        )

        service.register_tag(request)

        assert user_repo.patches[0]["preferred_scope"] == "user"


# ==============================================================================
# Issue #78-2: user scope で translations が保存される
# ==============================================================================


class TestUserScopeTranslations:
    @pytest.mark.db_tools
    def test_translations_saved_as_patches(self):
        reader = DummyUserReader()
        service, user_repo = _make_user_service(reader)
        request = TagRegisterRequest(
            tag="foo",
            source_tag="foo",
            format_name="danbooru",
            type_name="general",
            scope="user",
            translations=[
                TagTranslationInput(language="ja", translation="フー"),
                TagTranslationInput(language="en", translation="foo-en"),
            ],
        )

        result = service.register_tag(request)

        assert result.created is True
        langs = {(p["language"], p["translation"]) for p in user_repo.translation_patches}
        assert langs == {("ja", "フー"), ("en", "foo-en")}
        for patch in user_repo.translation_patches:
            assert patch["target_scope"] == "user"
            assert patch["target_tag_id"] == result.tag_id
