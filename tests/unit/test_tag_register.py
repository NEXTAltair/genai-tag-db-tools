import polars as pl
import pytest

from genai_tag_db_tools.services.tag_register import TagRegister
from genai_tag_db_tools.utils.cleanup_str import TagCleaner


@pytest.mark.db_tools
def test_normalize_tags_fills_missing_fields():
    register = TagRegister(repository=None)
    df = pl.DataFrame(
        {
            "source_tag": ["", "orig_tag"],
            "tag": ["hello_world", ""],
        }
    )

    result = register.normalize_tags(df)

    assert result["source_tag"].to_list() == ["hello_world", "orig_tag"]
    assert result["tag"].to_list() == ["hello_world", TagCleaner.clean_format("orig_tag")]


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
    df = pl.DataFrame(
        {"tag_id": [10], "deprecated_tags": ["old_tag, old_tag2,  "]}
    )

    register.update_deprecated_tags(df, format_id=3)

    cleaned = [TagCleaner.clean_format("old_tag"), TagCleaner.clean_format("old_tag2")]
    assert repo.created == [(cleaned[0], cleaned[0]), (cleaned[1], cleaned[1])]
    assert repo.status_updates == [(201, 3, True, 10), (202, 3, True, 10)]
