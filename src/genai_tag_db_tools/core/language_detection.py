"""Translation language detection for short tag translations.

This module provides a thin, well-tested abstraction over a short-text language
detector. It is used to decide whether a ``ja`` translation field actually looks
Japanese, Chinese, English or undetermined, exposing a ``confidence`` value and an
``is_ambiguous`` signal so callers can drop uncertain cases to review-only instead
of asserting ``wrong_language_translation``.

Design notes / why this is a hybrid
------------------------------------
The issue (#88) suggested ``lingua-language-detector`` for short-text detection.
``lingua`` is used here as the primary engine for non-CJK text and as the source
of confidence values. However, ``lingua`` (like every statistical detector tried)
classifies *Han-only* short strings as Chinese regardless of whether they are
natural Japanese kanji words: ``黄色``, ``青色``, ``猫``, ``和服`` all score
``CHINESE`` with confidence ``1.0`` -- identical to genuinely Chinese ``蓝色眼睛``.
There is therefore no confidence/margin threshold that separates Japanese kanji
words from Chinese for Han-only input.

To stay correct we combine signals:

* Kana (Hiragana/Katakana) present -> Japanese (decisive).
* A *Chinese-specific* character present -> Chinese (decisive). This replaces the
  ad-hoc ``_ZH_SPECIFIC_CHARS`` check that previously lived in ``core_api``. The
  set is a curated collection of simplified-Chinese-only characters that are not
  used in modern Japanese; it acts as the *fallback / gating* signal as allowed by
  the issue's acceptance criteria.
* Han-only with no Chinese-specific character -> treated as Japanese-compatible
  (``is_ambiguous=True``) and never asserted as Chinese, so natural Japanese kanji
  words are not false-positives.
* Otherwise (Latin etc.) -> defer to ``lingua`` when available, falling back to a
  pure script heuristic.

The whole thing sits behind :class:`TranslationLanguageDetector` so the ``lingua``
integration can be swapped or removed cleanly. When ``lingua`` is not installed a
:class:`ScriptHeuristicLanguageDetector` is used transparently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CHINESE_SPECIFIC_CHARS",
    "DetectedLanguage",
    "LanguageDetectionResult",
    "LinguaLanguageDetector",
    "ScriptHeuristicLanguageDetector",
    "TranslationLanguageDetector",
    "detect_translation_language",
    "get_detector",
]

_KANA_PATTERN = re.compile(r"[぀-ヿ]")
_HAN_PATTERN = re.compile(r"[㐀-鿿豈-﫿]")
_LATIN_ALPHA_PATTERN = re.compile(r"[A-Za-z]")

# Curated set of simplified-Chinese-only characters that do not appear in modern
# Japanese writing. Presence of any of these in an otherwise Han-only string is a
# strong, low-maintenance signal that the text is Chinese rather than Japanese.
# This is intentionally a *gating/fallback* signal, not an exhaustive dictionary.
CHINESE_SPECIFIC_CHARS = frozenset(
    "们这为么发头见观蓝绿红龙马门风鸟鱼脸长单师网让边过还进车东应电话语说译"
    "图团园课实间问难题颜爱乐习时觉现样资质贝贵费钟银错镜组级纪约纳纸线练经给"
    "绍续维罗妈爸哥姐弟妹钱铁钢银货买卖东应义乡书将专丧丰临举"
)

# Below this top-vs-second confidence margin a non-CJK detection is treated as
# ambiguous.
_AMBIGUOUS_MARGIN = 0.10


class DetectedLanguage(str, Enum):
    """Languages this detector can report for a translation field."""

    JAPANESE = "ja"
    CHINESE = "zh"
    ENGLISH = "en"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LanguageDetectionResult:
    """Result of classifying a short translation string.

    Attributes:
        language: Best-guess language, or ``UNKNOWN`` when undetermined.
        confidence: Confidence in ``[0.0, 1.0]`` for ``language``.
        is_ambiguous: ``True`` when the verdict should not be trusted to assert a
            wrong-language decision (e.g. Han-only text that could be either
            Japanese or Chinese, or a close call between candidates).
    """

    language: DetectedLanguage
    confidence: float
    is_ambiguous: bool


@runtime_checkable
class TranslationLanguageDetector(Protocol):
    """Protocol for a short-text translation language detector."""

    def detect(self, text: str) -> LanguageDetectionResult: ...


@dataclass(frozen=True)
class _ScriptProfile:
    has_kana: bool
    has_han: bool
    has_latin: bool
    has_chinese_specific: bool
    has_alnum: bool


def _profile(text: str) -> _ScriptProfile:
    return _ScriptProfile(
        has_kana=bool(_KANA_PATTERN.search(text)),
        has_han=bool(_HAN_PATTERN.search(text)),
        has_latin=bool(_LATIN_ALPHA_PATTERN.search(text)),
        has_chinese_specific=any(char in CHINESE_SPECIFIC_CHARS for char in text),
        has_alnum=any(char.isalnum() for char in text),
    )


_UNKNOWN_RESULT = LanguageDetectionResult(DetectedLanguage.UNKNOWN, 0.0, False)
_JAPANESE_KANA_RESULT = LanguageDetectionResult(DetectedLanguage.JAPANESE, 0.99, False)
# Han-only, Japanese-compatible kanji with no Chinese-specific character. Leaned
# Japanese but flagged ambiguous so it is never asserted as Chinese.
_JAPANESE_HAN_RESULT = LanguageDetectionResult(DetectedLanguage.JAPANESE, 0.5, True)


def _script_gate(profile: _ScriptProfile) -> LanguageDetectionResult | None:
    """Return a decisive result from script analysis, or ``None`` to defer.

    Shared by both detector implementations so the Japanese/Chinese decision is
    identical with or without ``lingua``.
    """
    if not profile.has_alnum:
        return _UNKNOWN_RESULT
    if profile.has_kana:
        return _JAPANESE_KANA_RESULT
    if profile.has_chinese_specific:
        return LanguageDetectionResult(DetectedLanguage.CHINESE, 0.95, False)
    if profile.has_han:
        return _JAPANESE_HAN_RESULT
    return None


class ScriptHeuristicLanguageDetector:
    """Dependency-free fallback detector based purely on script analysis.

    Used when ``lingua-language-detector`` is not installed. It is deterministic
    and good enough for the Japanese/Chinese/English/unknown distinction this
    project needs.
    """

    def detect(self, text: str) -> LanguageDetectionResult:
        stripped = text.strip()
        if not stripped:
            return _UNKNOWN_RESULT
        profile = _profile(stripped)
        gated = _script_gate(profile)
        if gated is not None:
            return gated
        if profile.has_latin:
            return LanguageDetectionResult(DetectedLanguage.ENGLISH, 0.9, False)
        return _UNKNOWN_RESULT


_LINGUA_NAME_TO_LANGUAGE = {
    "JAPANESE": DetectedLanguage.JAPANESE,
    "CHINESE": DetectedLanguage.CHINESE,
    "ENGLISH": DetectedLanguage.ENGLISH,
}


class LinguaLanguageDetector:
    """Detector backed by ``lingua-language-detector``.

    ``lingua`` is the primary engine for non-CJK text and the source of confidence
    values. The Japanese/Chinese decision for kana/Han-only input is still driven
    by :func:`_script_gate` because ``lingua`` cannot distinguish Japanese kanji
    words from Chinese in short Han-only strings (see module docstring).
    """

    def __init__(self, lingua_detector: Any) -> None:
        self._lingua = lingua_detector

    def detect(self, text: str) -> LanguageDetectionResult:
        stripped = text.strip()
        if not stripped:
            return _UNKNOWN_RESULT
        profile = _profile(stripped)
        gated = _script_gate(profile)
        if gated is not None:
            # Refine confidence from lingua for the decisive Chinese case while
            # keeping the script verdict authoritative.
            if gated.language is DetectedLanguage.CHINESE:
                confidence = max(gated.confidence, self._confidence(stripped, "CHINESE"))
                return LanguageDetectionResult(DetectedLanguage.CHINESE, confidence, False)
            return gated
        return self._detect_non_cjk(stripped)

    def _detect_non_cjk(self, text: str) -> LanguageDetectionResult:
        values = list(self._lingua.compute_language_confidence_values(text))
        if not values:
            return LanguageDetectionResult(DetectedLanguage.UNKNOWN, 0.0, True)
        top = values[0]
        language = _LINGUA_NAME_TO_LANGUAGE.get(top.language.name, DetectedLanguage.UNKNOWN)
        second_value = values[1].value if len(values) > 1 else 0.0
        is_ambiguous = (top.value - second_value) < _AMBIGUOUS_MARGIN
        return LanguageDetectionResult(language, top.value, is_ambiguous)

    def _confidence(self, text: str, language_name: str) -> float:
        for value in self._lingua.compute_language_confidence_values(text):
            if value.language.name == language_name:
                return float(value.value)
        return 0.0


@lru_cache(maxsize=1)
def get_detector() -> TranslationLanguageDetector:
    """Return a cached detector, preferring ``lingua`` when importable.

    Building the ``lingua`` detector is relatively expensive, so the result is
    cached for the process. Falls back to :class:`ScriptHeuristicLanguageDetector`
    when ``lingua-language-detector`` is unavailable.
    """
    try:
        from lingua import Language, LanguageDetectorBuilder
    except Exception:
        return ScriptHeuristicLanguageDetector()

    lingua_detector = LanguageDetectorBuilder.from_languages(
        Language.JAPANESE,
        Language.CHINESE,
        Language.ENGLISH,
    ).build()
    return LinguaLanguageDetector(lingua_detector)


def detect_translation_language(text: str) -> LanguageDetectionResult:
    """Classify ``text`` into Japanese / Chinese / English / unknown."""
    return get_detector().detect(text)
