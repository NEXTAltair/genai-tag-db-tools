import pytest
from genai_tag_db_tools.utils.cleanup_str import TagCleaner


@pytest.fixture
def tag_cleaner():
    return TagCleaner()


def test_clean_format(tag_cleaner):
    text = "This is a test. This is only a test."
    expected = "This is a test, This is only a test,"
    assert TagCleaner.clean_format(text) == expected


def test_clean_format_01(tag_cleaner):
    text = "This_is_a_test.\n (This) is only a test."
    expected = r"This is a test, \(This\) is only a test,"
    assert TagCleaner.clean_format(text) == expected


def test_clean_tags(tag_cleaner):
    tags = "long hair, black hair, anime style, white shirt, shirt, 1girl"
    expected = "long hair, black hair, anime, white shirt, 1girl"
    assert tag_cleaner.clean_tags(tags) == expected


def test_clean_tags_girls(tag_cleaner):
    """複数人物がいる場合のテストは色のタグを削除する"""
    tags = "long hair, short hair, anime style, white shirt, shirt, 2girls, black hair, red eyes"
    expected = "long hair, short hair, anime, white shirt, 2girls"
    assert tag_cleaner.clean_tags(tags) == expected


def test_clean_repetition(tag_cleaner):
    text = "This is a test,,,,,, with multiple spaces    and backslashes\\\\\\"
    expected = "This is a test, with multiple spaces and backslashes\\"
    assert tag_cleaner._clean_repetition(text) == expected


def test_clean_underscore(tag_cleaner):
    text = "This_is_a_test_with_^_^_underscores"
    expected = "This is a test with ^_^ underscores"
    assert tag_cleaner._clean_underscore(text) == expected


def test_tags_to_dict(tag_cleaner):
    tags = "tag1, tag2, tag1, tag3"
    expected = {0: "tag1", 1: "tag2", 3: "tag3"}
    assert tag_cleaner._tags_to_dict(tags) == expected


def test_clean_individual_tags(tag_cleaner):
    tags_dict = {0: "long hair", 1: "blue eyes", 2: "short hair"}
    expected = {0: "long hair", 1: "", 2: "short hair"}
    assert tag_cleaner._clean_individual_tags(tags_dict) == expected


def test_clean_color_object(tag_cleaner):
    tags_dict = {0: "white shirt", 1: "shirt", 2: "blue shirt"}
    expected = {0: "white shirt", 2: "blue shirt"}
    assert tag_cleaner._clean_color_object(tags_dict) == expected


def test_clean_style(tag_cleaner):
    tags_dict = {0: "anime style", 1: "anime art", 2: "cartoon style"}
    expected = {0: "anime", 2: "cartoon"}
    assert tag_cleaner._clean_style(tags_dict) == expected
