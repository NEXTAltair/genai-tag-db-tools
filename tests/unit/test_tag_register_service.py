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

    def get_format_id(self, format_name: str) -> int | None:
        return {"danbooru": 1}.get(format_name)

    def get_type_id(self, type_name: str) -> int | None:
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


class DummyReader:
    def __init__(self, repo: DummyRepo) -> None:
        self.repo = repo

    def get_format_id(self, format_name: str) -> int | None:
        return self.repo.get_format_id(format_name)

    def get_type_id(self, type_name: str) -> int | None:
        return self.repo.get_type_id(type_name)

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
    tag_info = {
        "normalized_tag": "foo",
        "source_tag": "foo",
        "format_name": "danbooru",
        "type_name": "general",
        "use_count": 12,
        "language": "ja",
        "translation": "フー",
    }

    tag_id = service.register_or_update_tag(tag_info)

    assert tag_id == 10
    assert repo.usage_updates == [(10, 1, 12)]
