import pytest

from genai_tag_db_tools.utils.cleanup_str import TagCleaner

pytestmark = pytest.mark.db_tools


def test_clean_format_escapes_parens_and_underscores() -> None:
    assert TagCleaner.clean_format("foo_bar (baz)") == r"foo bar \(baz\)"


def test_clean_format_preserves_kaomoji() -> None:
    assert TagCleaner.clean_format("^_^") == "^_^"


def test_clean_repetition_collapses_commas_and_spaces() -> None:
    assert TagCleaner._clean_repetition("a,,  b") == "a, b"


def test_clean_tags_deduplicates() -> None:
    assert TagCleaner.clean_tags("cat, cat") == "cat"


def test_clean_caption_strips_spaces_and_commas() -> None:
    assert TagCleaner.clean_caption(" hello , ") == "hello"
