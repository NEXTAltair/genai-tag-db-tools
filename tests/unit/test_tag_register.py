import polars as pl
import pytest
from pydantic import ValidationError

from genai_tag_db_tools.models import TagRegisterRequest
from genai_tag_db_tools.services.tag_register import TagRegister, TagRegisterService
from genai_tag_db_tools.utils.cleanup_str import TagCleaner


@pytest.mark.db_tools
def test_normalize_tags_fills_missing_fields():
    class DummyRepo:
        pass

    register = TagRegister(repository=DummyRepo())
    df = pl.DataFrame(
        {
            "source_tag": ["", "orig_tag"],
            "tag": ["hello_world", ""],
        }
    )

    result = register.normalize_tags(df)

    assert result["source_tag"].to_list() == ["hello_world", "orig_tag"]
    assert result["tag"].to_list() == [
        TagCleaner.clean_format("hello_world"),
        TagCleaner.clean_format("orig_tag"),
    ]


@pytest.mark.db_tools
def test_normalize_tags_normalizes_non_empty_tag():
    class DummyRepo:
        pass

    register = TagRegister(repository=DummyRepo())
    df = pl.DataFrame({"source_tag": [""], "tag": ["blue__eyes"]})

    result = register.normalize_tags(df)

    assert result["source_tag"].to_list() == ["blue__eyes"]
    assert result["tag"].to_list() == ["blue eyes"]


@pytest.mark.db_tools
def test_insert_tags_and_attach_id_uses_existing_map():
    class DummyRepo:
        def __init__(self):
            self.bulk_inserted = None

        def bulk_insert_tags(self, df: pl.DataFrame) -> None:
            self.bulk_inserted = df

        def _fetch_existing_tags_as_map(self, tags: list[str]) -> dict[str, int]:
            return {tag: idx + 100 for idx, tag in enumerate(tags)}

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"source_tag": ["a", "b"], "tag": ["a", "b"]})

    result = register.insert_tags_and_attach_id(df)

    assert repo.bulk_inserted is not None
    assert set(result["tag_id"].to_list()) == {100, 101}


@pytest.mark.db_tools
@pytest.mark.parametrize("tag", ["", "   ", "#"])
def test_insert_tags_and_attach_id_rejects_empty_normalized_tag(tag: str):
    class DummyRepo:
        def __init__(self):
            self.bulk_inserted = None

        def bulk_insert_tags(self, df: pl.DataFrame) -> None:
            self.bulk_inserted = df

        def _fetch_existing_tags_as_map(self, tags: list[str]) -> dict[str, int]:
            return {}

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"source_tag": [tag], "tag": [tag]})

    with pytest.raises(ValueError, match="empty after normalization"):
        register.insert_tags_and_attach_id(df)

    assert repo.bulk_inserted is None


@pytest.mark.db_tools
def test_insert_tags_and_attach_id_stores_normalized_tag():
    class DummyRepo:
        def __init__(self):
            self.bulk_inserted = None

        def bulk_insert_tags(self, df: pl.DataFrame) -> None:
            self.bulk_inserted = df

        def _fetch_existing_tags_as_map(self, tags: list[str]) -> dict[str, int]:
            return {tag: idx + 100 for idx, tag in enumerate(tags)}

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"source_tag": ["blue__eyes"], "tag": ["blue__eyes"]})

    result = register.insert_tags_and_attach_id(df)

    assert repo.bulk_inserted is not None
    assert repo.bulk_inserted["tag"].to_list() == ["blue eyes"]
    assert result["tag"].to_list() == ["blue eyes"]


@pytest.mark.db_tools
def test_update_usage_counts_skips_missing_values():
    class DummyRepo:
        def __init__(self):
            self.calls = []

        def update_usage_count(self, tag_id: int, format_id: int, count: int) -> None:
            self.calls.append((tag_id, format_id, count))

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"tag_id": [1, None, 3], "count": [10, 20, None]})

    register.update_usage_counts(df, format_id=2)

    assert repo.calls == [(1, 2, 10)]


@pytest.mark.db_tools
def test_update_translations_skips_empty_values():
    class DummyRepo:
        def __init__(self):
            self.calls = []

        def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
            self.calls.append((tag_id, language, translation))

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"tag_id": [1, 2, None], "translation": ["ja_tag", "", "ko_tag"]})

    register.update_translations(df, language="ja")

    assert repo.calls == [(1, "ja", "ja_tag")]


@pytest.mark.db_tools
def test_update_deprecated_tags_registers_aliases():
    class DummyRepo:
        def __init__(self):
            self.created = []
            self.status_updates = []

        def create_tag(self, tag: str, source_tag: str) -> int:
            self.created.append((tag, source_tag))
            return len(self.created) + 200

        def update_tag_status(
            self,
            tag_id: int,
            format_id: int,
            alias: bool,
            preferred_tag_id: int,
        ) -> None:
            self.status_updates.append((tag_id, format_id, alias, preferred_tag_id))

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"tag_id": [10], "deprecated_tags": ["old_tag, old_tag2,  "]})

    register.update_deprecated_tags(df, format_id=3)

    cleaned = [TagCleaner.clean_format("old_tag"), TagCleaner.clean_format("old_tag2")]
    assert repo.created == [(cleaned[0], cleaned[0]), (cleaned[1], cleaned[1])]
    assert repo.status_updates == [(201, 3, True, 10), (202, 3, True, 10)]


class DummyRegisterRepo:
    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.status_updates: list[tuple[int, int, bool, int, int | None]] = []
        self._tag_ids: dict[str, int] = {}

    def create_type_name_if_not_exists(self, type_name: str, description: str | None = None) -> int:
        return {"general": 1}.get(type_name, 0)

    def get_next_type_id(self, format_id: int) -> int:
        return 1

    def create_type_format_mapping_if_not_exists(
        self, format_id: int, type_id: int, type_name_id: int, description: str | None = None
    ) -> int:
        return type_id

    def create_format_if_not_exists(
        self, format_name: str, description: str | None = None, reader: object = None
    ) -> int:
        return 1

    def create_tag(self, source_tag: str, tag: str) -> int:
        self.created_tags.append((source_tag, tag))
        self._tag_ids[tag] = 10
        return 10

    def update_tag_status(
        self, tag_id: int, format_id: int, alias: bool, preferred_tag_id: int, type_id: int | None = None
    ) -> None:
        self.status_updates.append((tag_id, format_id, alias, preferred_tag_id, type_id))


class DummyRegisterReader:
    def __init__(self, repo: DummyRegisterRepo) -> None:
        self.repo = repo

    def get_format_id(self, format_name: str) -> int:
        return 1

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return {"general": 1}.get(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self.repo._tag_ids.get(tag)


@pytest.mark.db_tools
@pytest.mark.parametrize("tag", ["", "   ", "#"])
def test_tag_register_request_rejects_empty_normalized_tag(tag: str):
    with pytest.raises(ValidationError, match="empty after normalization"):
        TagRegisterRequest(tag=tag, format_name="danbooru", type_name="general")


@pytest.mark.db_tools
def test_register_tag_stores_normalized_tag():
    repo = DummyRegisterRepo()
    reader = DummyRegisterReader(repo)
    service = TagRegisterService(repository=repo, reader=reader)
    request = TagRegisterRequest(tag="blue__eyes", format_name="danbooru", type_name="general")

    result = service.register_tag(request)

    assert result.created is True
    assert repo.created_tags == [("blue__eyes", "blue eyes")]
    assert repo.status_updates == [(10, 1, False, 10, 1)]
