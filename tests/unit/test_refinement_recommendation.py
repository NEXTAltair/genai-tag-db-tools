from __future__ import annotations

from genai_tag_db_tools.core_api import needs_manual_refinement, recommend_manual_refinement


def _reason_codes(tag: str) -> list[str]:
    return [reason.code for reason in recommend_manual_refinement(tag).reasons]


def test_normal_concrete_tag_does_not_need_refinement():
    recommendation = recommend_manual_refinement("red rose")

    assert recommendation.source_tag == "red rose"
    assert recommendation.normalized_tag == "red rose"
    assert recommendation.needs_refinement is False
    assert recommendation.score == 0.0
    assert recommendation.reasons == []
    assert recommendation.suggestions == []


def test_normalization_change_adds_correction_candidate():
    recommendation = recommend_manual_refinement("blue__eyes")

    assert recommendation.needs_refinement is True
    assert recommendation.score == 0.8
    assert recommendation.normalized_tag == "blue eyes"
    assert _reason_codes("blue__eyes") == ["normalization_changes_tag"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [
        ("correction_candidate", "blue eyes")
    ]


def test_parentheses_normalization_suggests_existing_cleaned_result():
    recommendation = recommend_manual_refinement("foo_bar (baz)")

    assert recommendation.needs_refinement is True
    assert recommendation.normalized_tag == r"foo bar \(baz\)"
    assert _reason_codes("foo_bar (baz)") == ["normalization_changes_tag"]
    assert recommendation.suggestions[0].kind == "correction_candidate"
    assert recommendation.suggestions[0].tag == r"foo bar \(baz\)"


def test_broad_single_word_is_review_only_without_correction_candidate():
    recommendation = recommend_manual_refinement("flower")

    assert recommendation.needs_refinement is True
    assert recommendation.score == 0.6
    assert recommendation.normalized_tag == "flower"
    assert _reason_codes("flower") == ["broad_single_word"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [("review_only", None)]


def test_site_info_token_is_review_only():
    recommendation = recommend_manual_refinement("__commentary_request")

    assert recommendation.needs_refinement is True
    assert recommendation.score == 0.6
    assert recommendation.normalized_tag == "commentary request"
    assert _reason_codes("__commentary_request") == ["site_info_token"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [("review_only", None)]


def test_empty_normalized_tag_is_review_only():
    recommendation = recommend_manual_refinement("___")

    assert recommendation.needs_refinement is True
    assert recommendation.score == 1.0
    assert recommendation.normalized_tag == ""
    assert _reason_codes("___") == ["empty_normalized_tag"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [("review_only", None)]


def test_needs_manual_refinement_is_thin_helper():
    recommendation = recommend_manual_refinement("blue__eyes")

    assert needs_manual_refinement("blue__eyes") is recommendation.needs_refinement
    assert needs_manual_refinement("red rose") is False


def test_reason_code_stability():
    assert _reason_codes("") == ["empty_normalized_tag"]
    assert _reason_codes("blue__eyes") == ["normalization_changes_tag"]
    assert _reason_codes("flower") == ["broad_single_word"]
    assert _reason_codes("__commentary_request") == ["site_info_token"]


def test_mixed_case_ordinary_tag_uses_canonical_lowercase_candidate():
    recommendation = recommend_manual_refinement("Blue Eyes")

    assert recommendation.needs_refinement is True
    assert recommendation.normalized_tag == "blue eyes"
    assert _reason_codes("Blue Eyes") == ["normalization_changes_tag"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [
        ("correction_candidate", "blue eyes")
    ]


def test_angle_bracket_token_case_is_preserved():
    recommendation = recommend_manual_refinement("<lora:CharacterName:0.8>")

    assert recommendation.normalized_tag == "<lora:CharacterName:0.8>"
    assert recommendation.needs_refinement is False


def test_site_metadata_id_token_is_review_only():
    recommendation = recommend_manual_refinement("pixiv_id")

    assert recommendation.needs_refinement is True
    assert recommendation.normalized_tag == "pixiv id"
    assert _reason_codes("pixiv_id") == ["site_info_token"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [("review_only", None)]


def test_suggestion_kind_is_structured():
    correction = recommend_manual_refinement("blue__eyes").suggestions[0]
    review = recommend_manual_refinement("flower").suggestions[0]

    assert correction.kind == "correction_candidate"
    assert correction.tag == "blue eyes"
    assert review.kind == "review_only"
    assert review.tag is None
