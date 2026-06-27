from __future__ import annotations

import pytest

from genai_tag_db_tools.core_api import recommend_translation_quality
from genai_tag_db_tools.models import TagRef


def _reason_codes(source_tag: str, translation: str | None, language: str = "ja") -> list[str]:
    recommendation = recommend_translation_quality(source_tag, translation, language=language)
    return [reason.code for reason in recommendation.reasons]


def test_valid_ja_translation_has_no_recommendation():
    recommendation = recommend_translation_quality(
        "blue eyes",
        "青い目",
        target_scope="base",
        target_tag_id=10,
    )

    assert recommendation.needs_refinement is False
    assert recommendation.score == 0.0
    assert recommendation.reasons == []
    assert recommendation.suggestions == []
    assert recommendation.proposals == []


def test_missing_translation_returns_reason_and_evidence_without_proposal_target():
    recommendation = recommend_translation_quality("blue eyes", " ")

    assert recommendation.needs_refinement is True
    assert recommendation.proposals == []
    assert recommendation.reasons[0].code == "missing_translation"
    assert recommendation.reasons[0].field == "translation.ja"
    assert recommendation.reasons[0].evidence == [
        {
            "field": "translation.ja",
            "language": "ja",
            "source_tag": "blue eyes",
            "translation": " ",
        }
    ]


def test_chinese_like_value_in_ja_translation_is_wrong_language():
    recommendation = recommend_translation_quality(
        "blue eyes",
        "蓝色眼睛",
        target_scope="base",
        target_tag_id=20,
    )

    assert [reason.code for reason in recommendation.reasons] == ["wrong_language_translation"]
    assert recommendation.reasons[0].field == "translation.ja"
    assert recommendation.proposals[0].kind == "translation_correction"
    assert recommendation.proposals[0].target.kind == "translation"
    assert recommendation.proposals[0].target.target_scope == "base"
    assert recommendation.proposals[0].target.target_tag_id == 20
    assert recommendation.proposals[0].target.language == "ja"
    assert recommendation.proposals[0].current == {
        "field": "translation.ja",
        "language": "ja",
        "translation": "蓝色眼睛",
    }
    assert recommendation.proposals[0].proposed is None
    assert recommendation.proposals[0].reason_codes == ["wrong_language_translation"]


def test_english_only_value_in_ja_translation_is_wrong_language_and_mismatch():
    assert _reason_codes("blue eyes", "blue eyes") == [
        "wrong_language_translation",
        "translation_mismatch",
    ]


def test_overlong_and_description_like_translation_are_detected():
    recommendation = recommend_translation_quality(
        "blue eyes",
        "青い目について説明するための長すぎる翻訳文です。タグ翻訳としては説明的です。",
    )

    assert [reason.code for reason in recommendation.reasons] == [
        "overlong_translation",
        "description_like_translation",
    ]
    assert all(reason.field == "translation.ja" for reason in recommendation.reasons)
    assert all(reason.evidence for reason in recommendation.reasons)


def test_low_quality_translation_is_review_only_without_auto_fix_candidate():
    recommendation = recommend_translation_quality("blue eyes", "N/A")

    assert "low_quality_translation" in [reason.code for reason in recommendation.reasons]
    assert recommendation.suggestions[0].kind == "review_only"
    assert recommendation.suggestions[0].tag is None


def test_tag_ref_can_supply_overlay_patch_target():
    recommendation = recommend_translation_quality(
        "cat",
        "cat",
        tag_ref=TagRef(scope="user", tag_id=1_000_000_001),
    )

    proposal = recommendation.proposals[0]
    assert proposal.target.target_scope == "user"
    assert proposal.target.target_tag_id == 1_000_000_001
    assert proposal.target.language == "ja"
    assert proposal.evidence[0]["target_scope"] == "user"
    assert proposal.evidence[0]["target_tag_id"] == 1_000_000_001


def test_partial_target_arguments_are_rejected():
    with pytest.raises(ValueError, match="target_scope and target_tag_id"):
        recommend_translation_quality("cat", "猫", target_scope="base")


def test_tag_ref_conflicting_target_arguments_are_rejected():
    with pytest.raises(ValueError, match="target_scope conflicts"):
        recommend_translation_quality(
            "cat",
            "猫",
            target_scope="base",
            tag_ref=TagRef(scope="user", tag_id=1_000_000_001),
        )
