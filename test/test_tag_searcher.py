import pytest
from pathlib import Path
from TagSearcher import TagSearcher
import pandas as pd


@pytest.fixture
def tag_searcher():
    db_path = Path("tags_v3.db")
    return TagSearcher(db_path)


def test_find_tag_id(tag_searcher):
    # 存在するタグのテスト
    tag_id = tag_searcher.find_tag_id("existing_tag")
    assert tag_id == expected_tag_id  # expected_tag_idを実際のIDに置き換えてください

    # 存在しないタグのテスト
    tag_id = tag_searcher.find_tag_id("non_existing_tag")
    assert tag_id is None


def test_search_tags(tag_searcher):
    result = tag_searcher.search_tags(
        "example", match_mode="partial", format_name="All"
    )
    assert isinstance(result, pd.DataFrame)
    assert not result.empty


def test_get_tag_details(tag_searcher):
    tag_details = tag_searcher.get_tag_details(1)  # 存在するタグIDを使用
    assert isinstance(tag_details, pd.DataFrame)
    assert not tag_details.empty


def test_create_tag(tag_searcher):
    new_tag = "test_new_tag"
    source_tag = "test_source_tag"
    tag_id = tag_searcher.create_tag(new_tag, source_tag)
    assert tag_id is not None


def test_update_tag_status(tag_searcher):
    tag_id = 1  # 既存のタグIDを使用
    format_id = 1  # 既存のフォーマットIDを使用
    type_id = 1  # 既存のタイプIDを使用
    alias = False
    preferred_tag_id = None
    updated_tag_id = tag_searcher.update_tag_status(
        tag_id, format_id, type_id, alias, preferred_tag_id
    )
    assert updated_tag_id == tag_id


def test_convert_prompt(tag_searcher):
    prompt = "1boy, 1girl"
    format_name = "e621"
    converted_prompt = tag_searcher.convert_prompt(prompt, format_name)
    assert isinstance(converted_prompt, str)
    assert converted_prompt != ""


def test_get_all_tag_ids(tag_searcher):
    tag_ids = tag_searcher.get_all_tag_ids()
    assert isinstance(tag_ids, list)
    assert len(tag_ids) > 0


def test_get_tag_formats(tag_searcher):
    formats = tag_searcher.get_tag_formats()
    assert isinstance(formats, list)
    assert "All" in formats


def test_get_tag_languages(tag_searcher):
    languages = tag_searcher.get_tag_languages()
    assert isinstance(languages, list)
    assert "All" in languages


def test_get_tag_types(tag_searcher):
    types = tag_searcher.get_tag_types("e621")
    assert isinstance(types, list)
