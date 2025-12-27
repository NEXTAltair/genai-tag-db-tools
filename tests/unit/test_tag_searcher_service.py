import polars as pl
import pytest

from genai_tag_db_tools.services.tag_search import TagSearcher


@pytest.mark.db_tools
def test_search_tags_returns_dataframe():
    class DummyReader:
        def search_tags(self, *args, **kwargs):
            return [{"tag": "cat", "tag_id": 1}]

    searcher = TagSearcher(reader=DummyReader())
    result = searcher.search_tags("cat")

    assert isinstance(result, pl.DataFrame)
    assert result.height == 1
    assert result["tag"].to_list() == ["cat"]


@pytest.mark.db_tools
def test_search_tags_empty_returns_empty_dataframe():
    class DummyReader:
        def search_tags(self, *args, **kwargs):
            return []

    searcher = TagSearcher(reader=DummyReader())
    result = searcher.search_tags("missing")

    assert isinstance(result, pl.DataFrame)
    assert result.height == 0


@pytest.mark.db_tools
def test_convert_tag_returns_original_when_missing():
    class DummyReader:
        pass

    searcher = TagSearcher(reader=DummyReader())
    with pytest.raises(NotImplementedError):
        searcher.convert_tag("original", 1)


@pytest.mark.db_tools
def test_convert_tag_uses_preferred_tag():
    class DummyReader:
        pass

    searcher = TagSearcher(reader=DummyReader())
    with pytest.raises(NotImplementedError):
        searcher.convert_tag("original", 1)


@pytest.mark.db_tools
def test_convert_tag_skips_invalid_target():
    class DummyReader:
        pass

    searcher = TagSearcher(reader=DummyReader())
    with pytest.raises(NotImplementedError):
        searcher.convert_tag("original", 1)


@pytest.mark.db_tools
def test_get_tag_types_returns_empty_when_missing_format():
    class DummyReader:
        def get_format_id(self, *args, **kwargs):
            return 0

    searcher = TagSearcher(reader=DummyReader())
    assert searcher.get_tag_types("missing") == []


@pytest.mark.db_tools
def test_get_format_id_none_returns_zero():
    class DummyReader:
        pass

    searcher = TagSearcher(reader=DummyReader())
    with pytest.raises(NotImplementedError):
        searcher.get_format_id(None)
