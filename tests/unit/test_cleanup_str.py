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


def test_convert_prompt_uses_tag_searcher() -> None:
    class DummySearcher:
        def get_format_id(self, format_name: str) -> int | None:
            return 1

        def convert_tag(self, tag: str, format_id: int) -> str:
            return f"{tag}-x"

    class DummyCleaner:
        tag_searcher = DummySearcher()

    dummy = DummyCleaner()
    assert TagCleaner.convert_prompt(dummy, "a, b", "danbooru") == "a-x, b-x"


def test_convert_prompt_returns_original_when_format_missing() -> None:
    class DummySearcher:
        def get_format_id(self, format_name: str) -> int | None:
            return None

    class DummyCleaner:
        tag_searcher = DummySearcher()

    dummy = DummyCleaner()
    assert TagCleaner.convert_prompt(dummy, "a, b", "unknown") == "a, b"
