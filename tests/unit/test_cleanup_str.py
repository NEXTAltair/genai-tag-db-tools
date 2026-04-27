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


# ---- ISSUE #11: angle bracket 構文（LoRA 等）の保護 ----


def test_clean_format_preserves_lora_case() -> None:
    """LoRA 記法の大文字小文字が保持される。"""
    assert TagCleaner.clean_format("<lora:CharacterName:0.8>") == "<lora:CharacterName:0.8>"


def test_clean_format_preserves_lora_underscore() -> None:
    """LoRA 記法のアンダースコアが保持される。"""
    assert TagCleaner.clean_format("<lora:Character_v1:0.8>") == "<lora:Character_v1:0.8>"


def test_clean_format_preserves_multiple_lora() -> None:
    """複数の LoRA 記法が個別に保護される。"""
    text = "masterpiece, <lora:A_v1:0.5>, <lora:B_v2:0.8>, blue eyes"
    result = TagCleaner.clean_format(text)
    assert "<lora:A_v1:0.5>" in result
    assert "<lora:B_v2:0.8>" in result


def test_clean_format_preserves_lyco_and_embedding() -> None:
    """lyco/embedding 等の他の angle bracket 構文も保護される。"""
    assert TagCleaner.clean_format("<lyco:Style_X:0.5>") == "<lyco:Style_X:0.5>"
    assert TagCleaner.clean_format("<embedding:NegEmb_v1>") == "<embedding:NegEmb_v1>"


def test_clean_format_protects_lora_with_anime_keyword() -> None:
    """LoRA 内に anime/cartoon/manga が含まれても破壊されない。"""
    assert TagCleaner.clean_format("<lora:AnimeStyle_v1:0.8>") == "<lora:AnimeStyle_v1:0.8>"


def test_clean_tags_preserves_lora_in_mixed_tags() -> None:
    """混在タグで LoRA が保持され通常タグは正規化される。"""
    result = TagCleaner.clean_tags("<lora:Char_v1:0.8>, cat, cat")
    assert "<lora:Char_v1:0.8>" in result
    assert "cat" in result


def test_clean_tags_lora_not_affected_by_style_unification() -> None:
    """`_clean_style` の anime 統一が LoRA タグには影響しない。"""
    result = TagCleaner.clean_tags("<lora:AnimeChar_v1:0.8>, anime art")
    assert "<lora:AnimeChar_v1:0.8>" in result
