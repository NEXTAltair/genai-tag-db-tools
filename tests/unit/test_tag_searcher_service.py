from types import SimpleNamespace

import polars as pl
import pytest

from genai_tag_db_tools.services.tag_search import TagSearcher


@pytest.mark.db_tools
def test_search_tags_returns_dataframe():
    class DummyRepo:
        def search_tags(self, *args, **kwargs):
            return [{"tag": "cat", "tag_id": 1}]

    searcher = TagSearcher(repository=DummyRepo())
    result = searcher.search_tags("cat")

    assert isinstance(result, pl.DataFrame)
    assert result.height == 1
    assert result["tag"].to_list() == ["cat"]


@pytest.mark.db_tools
def test_search_tags_empty_returns_empty_dataframe():
    class DummyRepo:
        def search_tags(self, *args, **kwargs):
            return []

    searcher = TagSearcher(repository=DummyRepo())
    result = searcher.search_tags("missing")

    assert isinstance(result, pl.DataFrame)
    assert result.height == 0


@pytest.mark.db_tools
def test_convert_tag_returns_original_when_missing():
    class DummyRepo:
        def get_tag_id_by_name(self, *args, **kwargs):
            return None

    searcher = TagSearcher(repository=DummyRepo())
    assert searcher.convert_tag("original", 1) == "original"


@pytest.mark.db_tools
def test_convert_tag_uses_preferred_tag():
    class DummyRepo:
        def get_tag_id_by_name(self, *args, **kwargs):
            return 10

        def get_tag_status(self, *args, **kwargs):
            return SimpleNamespace(preferred_tag_id=20)

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="preferred" if tag_id == 20 else "original")

    searcher = TagSearcher(repository=DummyRepo())
    assert searcher.convert_tag("original", 1) == "preferred"


@pytest.mark.db_tools
def test_convert_tag_skips_invalid_target():
    class DummyRepo:
        def get_tag_id_by_name(self, *args, **kwargs):
            return 10

        def get_tag_status(self, *args, **kwargs):
            return SimpleNamespace(preferred_tag_id=20)

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="invalid tag")

    searcher = TagSearcher(repository=DummyRepo())
    assert searcher.convert_tag("original", 1) == "original"


@pytest.mark.db_tools
def test_get_tag_types_returns_empty_when_missing_format():
    class DummyRepo:
        def get_format_id(self, *args, **kwargs):
            return 0

    searcher = TagSearcher(repository=DummyRepo())
    assert searcher.get_tag_types("missing") == []


@pytest.mark.db_tools
def test_get_format_id_none_returns_zero():
    class DummyRepo:
        def get_format_id(self, *args, **kwargs):
            return 99

    searcher = TagSearcher(repository=DummyRepo())
    assert searcher.get_format_id(None) == 0
