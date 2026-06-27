from __future__ import annotations

import pytest
from pydantic import ValidationError

from genai_tag_db_tools.core_api import recommend_manual_refinement
from genai_tag_db_tools.models import DbFeedbackProposal, ProposalTarget, RefinementRecommendation


def _proposal(
    *,
    kind: str = "tag_name_correction",
    target: ProposalTarget | None = None,
    current: dict[str, str | int | float | bool | None] | None = None,
    proposed: dict[str, str | int | float | bool | None] | None = None,
    reason_codes: list[str] | None = None,
) -> DbFeedbackProposal:
    return DbFeedbackProposal(
        kind=kind,
        target=target
        or ProposalTarget(kind="tag_name", target_scope="base", target_tag_id=100, format_name=None),
        current=current,
        proposed=proposed,
        confidence=0.8,
        source="unit_test",
        reason_codes=reason_codes or ["normalization_changes_tag"],
        evidence=[{"source_tag": "Blue Eyes", "normalized_tag": "blue eyes"}],
    )


def test_recommendation_has_empty_proposals_by_default():
    recommendation = recommend_manual_refinement("red rose")

    assert recommendation.proposals == []
    assert recommendation.model_dump()["proposals"] == []


def test_tag_name_correction_proposal_roundtrip():
    proposal = _proposal(
        current={"tag": "Blue Eyes"},
        proposed={"tag": "blue eyes"},
    )

    payload = proposal.model_dump()
    restored = DbFeedbackProposal.model_validate(payload)

    assert restored == proposal
    assert restored.kind == "tag_name_correction"
    assert restored.target.target_scope == "base"
    assert restored.target.target_tag_id == 100
    assert restored.requires_human_approval is True


def test_alias_addition_proposal_preserves_target_and_preferred_scopes():
    proposal = _proposal(
        kind="alias_addition",
        target=ProposalTarget(
            kind="alias",
            target_scope="user",
            target_tag_id=1_000_000_001,
            format_name="danbooru",
            preferred_scope="base",
            preferred_tag_id=42,
        ),
        current={"alias": False},
        proposed={"alias": True, "preferred_tag_id": 42, "preferred_scope": "base"},
        reason_codes=["duplicate_tag"],
    )

    restored = DbFeedbackProposal.model_validate_json(proposal.model_dump_json())

    assert restored.target.target_scope == "user"
    assert restored.target.target_tag_id == 1_000_000_001
    assert restored.target.preferred_scope == "base"
    assert restored.target.preferred_tag_id == 42
    assert restored.target.format_name == "danbooru"


def test_translation_correction_proposal_can_target_patch_shape():
    proposal = _proposal(
        kind="translation_correction",
        target=ProposalTarget(
            kind="translation",
            target_scope="base",
            target_tag_id=200,
            language="ja",
        ),
        current={"translation": "青目"},
        proposed={"translation": "青い目"},
        reason_codes=["translation_mismatch"],
    )

    assert proposal.target.kind == "translation"
    assert proposal.target.target_scope == "base"
    assert proposal.target.language == "ja"
    assert proposal.target.format_name is None


def test_usage_correction_proposal_uses_format_specific_target():
    proposal = _proposal(
        kind="usage_correction",
        target=ProposalTarget(
            kind="usage",
            target_scope="user",
            target_tag_id=1_000_000_002,
            format_name="unknown",
        ),
        current={"count": 0},
        proposed={"count": 12},
        reason_codes=["usage_count_mismatch"],
    )

    assert proposal.target.target_scope == "user"
    assert proposal.target.format_name == "unknown"


def test_status_correction_proposal_can_represent_training_unsuitable_as_deprecated():
    proposal = _proposal(
        kind="status_correction",
        target=ProposalTarget(
            kind="tag_status",
            target_scope="base",
            target_tag_id=300,
            format_name="unknown",
        ),
        current={"deprecated": False},
        proposed={"deprecated": True},
        reason_codes=["training_unsuitable"],
    )

    assert proposal.kind == "status_correction"
    assert proposal.reason_codes == ["training_unsuitable"]
    assert proposal.proposed == {"deprecated": True}


def test_format_name_none_and_unknown_are_distinct_in_serialization():
    global_target = ProposalTarget(kind="tag_name", target_scope="base", target_tag_id=1)
    unknown_format_target = ProposalTarget(
        kind="tag_status",
        target_scope="base",
        target_tag_id=1,
        format_name="unknown",
    )

    assert global_target.model_dump()["format_name"] is None
    assert unknown_format_target.model_dump()["format_name"] == "unknown"
    assert ProposalTarget.model_validate(global_target.model_dump()).format_name is None
    assert ProposalTarget.model_validate(unknown_format_target.model_dump()).format_name == "unknown"


def test_base_user_scope_is_preserved_in_recommendation_serialization_roundtrip():
    base_proposal = _proposal(
        target=ProposalTarget(kind="tag_name", target_scope="base", target_tag_id=10),
        current={"tag": "old base"},
        proposed={"tag": "new base"},
    )
    user_proposal = _proposal(
        kind="type_correction",
        target=ProposalTarget(
            kind="tag_type",
            target_scope="user",
            target_tag_id=1_000_000_010,
            format_name="unknown",
        ),
        current={"type_name": "unknown"},
        proposed={"type_name": "general"},
        reason_codes=["type_mismatch"],
    )
    recommendation = RefinementRecommendation(
        source_tag="Blue Eyes",
        normalized_tag="blue eyes",
        needs_refinement=True,
        score=0.8,
        proposals=[base_proposal, user_proposal],
    )

    restored = RefinementRecommendation.model_validate_json(recommendation.model_dump_json())

    assert [proposal.target.target_scope for proposal in restored.proposals] == ["base", "user"]
    assert restored.proposals[1].target.format_name == "unknown"
    assert restored == recommendation


def test_preferred_scope_and_tag_id_must_be_provided_together():
    with pytest.raises(ValidationError):
        ProposalTarget(
            kind="alias",
            target_scope="user",
            target_tag_id=1_000_000_001,
            preferred_scope="base",
        )
