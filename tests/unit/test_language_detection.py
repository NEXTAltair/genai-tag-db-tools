from __future__ import annotations

import pytest

from genai_tag_db_tools.core import language_detection
from genai_tag_db_tools.core.language_detection import (
    DetectedLanguage,
    LanguageDetectionResult,
    LinguaLanguageDetector,
    ScriptHeuristicLanguageDetector,
    TranslationLanguageDetector,
    detect_translation_language,
    get_detector,
)


def _lingua_available() -> bool:
    try:
        import lingua  # noqa: F401
    except Exception:
        return False
    return True


@pytest.fixture(params=["fallback", "active"])
def detector(request) -> TranslationLanguageDetector:
    """Run detection assertions against both the script fallback and the active detector."""
    if request.param == "fallback":
        return ScriptHeuristicLanguageDetector()
    return get_detector()


class TestSharedDetectionContract:
    """Assertions that must hold for every detector implementation."""

    def test_kana_is_japanese_and_not_ambiguous(self, detector: TranslationLanguageDetector) -> None:
        result = detector.detect("青い目")
        assert result.language is DetectedLanguage.JAPANESE
        assert result.is_ambiguous is False
        assert result.confidence > 0.5

    def test_katakana_is_japanese(self, detector: TranslationLanguageDetector) -> None:
        assert detector.detect("ネコ").language is DetectedLanguage.JAPANESE

    def test_chinese_specific_characters_are_chinese(self, detector: TranslationLanguageDetector) -> None:
        result = detector.detect("蓝色眼睛")
        assert result.language is DetectedLanguage.CHINESE
        assert result.is_ambiguous is False
        assert result.confidence >= 0.9

    @pytest.mark.parametrize("text", ["黄色", "青色", "猫", "和服"])
    def test_japanese_kanji_words_are_not_asserted_as_chinese(
        self, detector: TranslationLanguageDetector, text: str
    ) -> None:
        result = detector.detect(text)
        # Either Japanese, or at least never a confident Chinese verdict.
        assert not (result.language is DetectedLanguage.CHINESE and not result.is_ambiguous)

    def test_han_only_kanji_word_is_ambiguous(self, detector: TranslationLanguageDetector) -> None:
        # Pure Han kanji words cannot be reliably split into ja/zh -> ambiguous.
        result = detector.detect("猫")
        assert result.language is DetectedLanguage.JAPANESE
        assert result.is_ambiguous is True

    def test_english_text(self, detector: TranslationLanguageDetector) -> None:
        assert detector.detect("blue eyes").language is DetectedLanguage.ENGLISH

    def test_empty_or_symbol_only_is_unknown(self, detector: TranslationLanguageDetector) -> None:
        assert detector.detect("   ").language is DetectedLanguage.UNKNOWN
        assert detector.detect("!!!").language is DetectedLanguage.UNKNOWN

    def test_confidence_within_bounds(self, detector: TranslationLanguageDetector) -> None:
        for text in ["青い目", "蓝色眼睛", "blue eyes", "猫", ""]:
            result = detector.detect(text)
            assert 0.0 <= result.confidence <= 1.0


class TestScriptHeuristicFallback:
    def test_is_a_translation_language_detector(self) -> None:
        assert isinstance(ScriptHeuristicLanguageDetector(), TranslationLanguageDetector)

    def test_no_dependency_on_lingua(self) -> None:
        # The fallback must work without lingua being imported/used.
        detector = ScriptHeuristicLanguageDetector()
        assert detector.detect("漢字").language is DetectedLanguage.JAPANESE


class TestModuleApi:
    def test_detect_translation_language_uses_cached_detector(self) -> None:
        assert isinstance(get_detector(), TranslationLanguageDetector)
        result = detect_translation_language("蓝色眼睛")
        assert isinstance(result, LanguageDetectionResult)
        assert result.language is DetectedLanguage.CHINESE

    def test_get_detector_is_cached(self) -> None:
        assert get_detector() is get_detector()

    @pytest.mark.skipif(not _lingua_available(), reason="lingua-language-detector not installed")
    def test_active_detector_is_lingua_backed(self) -> None:
        assert isinstance(get_detector(), LinguaLanguageDetector)


class TestLinguaDetectorWithFakeBackend:
    """Exercise LinguaLanguageDetector decision paths with a fake lingua backend."""

    class _FakeLanguage:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeConfidence:
        def __init__(self, name: str, value: float) -> None:
            self.language = TestLinguaDetectorWithFakeBackend._FakeLanguage(name)
            self.value = value

    class _FakeLingua:
        def __init__(self, values: list[tuple[str, float]]) -> None:
            self._values = values

        def compute_language_confidence_values(self, _text: str):
            return [
                TestLinguaDetectorWithFakeBackend._FakeConfidence(name, value)
                for name, value in self._values
            ]

    def test_non_cjk_close_call_is_ambiguous(self) -> None:
        detector = LinguaLanguageDetector(self._FakeLingua([("ENGLISH", 0.52), ("JAPANESE", 0.48)]))
        result = detector.detect("abc")
        assert result.language is DetectedLanguage.ENGLISH
        assert result.is_ambiguous is True

    def test_non_cjk_clear_winner_is_not_ambiguous(self) -> None:
        detector = LinguaLanguageDetector(self._FakeLingua([("ENGLISH", 0.95), ("JAPANESE", 0.05)]))
        result = detector.detect("hello")
        assert result.language is DetectedLanguage.ENGLISH
        assert result.is_ambiguous is False

    def test_chinese_specific_char_overrides_lingua_and_refines_confidence(self) -> None:
        # Even if the fake backend reported nothing useful, the script gate decides.
        detector = LinguaLanguageDetector(self._FakeLingua([("CHINESE", 0.8)]))
        result = detector.detect("蓝色眼睛")
        assert result.language is DetectedLanguage.CHINESE
        assert result.confidence >= 0.9
        assert result.is_ambiguous is False

    def test_han_only_without_chinese_specific_is_ambiguous_japanese(self) -> None:
        # lingua would say CHINESE 1.0, but the gate keeps it Japanese/ambiguous.
        detector = LinguaLanguageDetector(self._FakeLingua([("CHINESE", 1.0)]))
        result = detector.detect("黄色")
        assert result.language is DetectedLanguage.JAPANESE
        assert result.is_ambiguous is True


def test_module_exposes_chinese_specific_chars() -> None:
    assert "蓝" in language_detection.CHINESE_SPECIFIC_CHARS
    # Characters shared with Japanese must not be in the gate set.
    for shared in "猫黄色青和服国学体":
        assert shared not in language_detection.CHINESE_SPECIFIC_CHARS
