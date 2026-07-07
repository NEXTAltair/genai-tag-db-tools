import polars as pl
import pytest

from genai_tag_db_tools.services.tag_register import TagRegister
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
def test_update_deprecated_tags_registers_aliases_atomically():
    """#1249: deprecated alias は create_tag→別 session の update_tag_status という非 atomic な
    分離ではなく、register_tag_with_status で TAGS 行と TAG_STATUS 行を単一トランザクションに
    束ねて登録する。低並行下で child(TAG_STATUS) が直前の parent(TAGS) を可視化できず
    FK 制約失敗になる潜在バグを塞ぐ。
    """

    class DummyRepo:
        def __init__(self):
            self.atomic_calls: list[dict] = []
            self.legacy_create_calls: list[tuple[str, str]] = []
            self.legacy_status_calls: list[dict] = []

        def register_tag_with_status(
            self,
            *,
            source_tag: str,
            tag: str,
            existing_tag_id: int | None,
            format_id: int,
            type_id: int | None,
            alias: bool,
            preferred_tag_id: int | None,
            translations: list[tuple[str, str]] | None = None,
        ) -> int:
            self.atomic_calls.append(
                {
                    "source_tag": source_tag,
                    "tag": tag,
                    "existing_tag_id": existing_tag_id,
                    "format_id": format_id,
                    "type_id": type_id,
                    "alias": alias,
                    "preferred_tag_id": preferred_tag_id,
                }
            )
            return len(self.atomic_calls) + 200

        def create_tag(self, source_tag: str, tag: str) -> int:  # 旧非 atomic 経路
            self.legacy_create_calls.append((source_tag, tag))
            return 999

        def update_tag_status(self, **kwargs) -> None:  # 旧非 atomic 経路
            self.legacy_status_calls.append(kwargs)

    repo = DummyRepo()
    register = TagRegister(repository=repo)
    df = pl.DataFrame({"tag_id": [10], "deprecated_tags": ["old_tag, old_tag2,  "]})

    register.update_deprecated_tags(df, format_id=3)

    cleaned = [TagCleaner.clean_format("old_tag"), TagCleaner.clean_format("old_tag2")]
    # 非 atomic な旧経路 (create_tag + update_tag_status の分離呼び出し) は使わない
    assert repo.legacy_create_calls == []
    assert repo.legacy_status_calls == []
    # 単一トランザクションの atomic 経路のみを使う
    assert [c["tag"] for c in repo.atomic_calls] == cleaned
    assert [c["source_tag"] for c in repo.atomic_calls] == cleaned
    for call in repo.atomic_calls:
        assert call["alias"] is True
        assert call["preferred_tag_id"] == 10
        assert call["format_id"] == 3
        # type_id=None で既存 status の値を保持し、新規なら 0 を使う従来挙動を維持
        assert call["type_id"] is None
        # existing_tag_id=None で session 内解決 (新規/既存の両対応) に委ねる
        assert call["existing_tag_id"] is None
