from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, inspect

from genai_tag_db_tools.db.schema import UserOverlayBase
from genai_tag_db_tools.models import (
    ApprovedDbFeedback,
    DbFeedbackProposal,
    LocalFeedbackApplicationRecord,
    LocalFeedbackApplyResult,
    ProposalTarget,
)


def _proposal() -> DbFeedbackProposal:
    return DbFeedbackProposal(
        kind="translation_correction",
        target=ProposalTarget(
            kind="translation",
            target_scope="base",
            target_tag_id=10,
            language="ja",
        ),
        current=None,
        proposed={"language": "ja", "translation": "青い目"},
        confidence=0.9,
        source="unit_test",
        reason_codes=["translation_mismatch"],
    )


def test_approved_db_feedback_roundtrip():
    approved_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    feedback = ApprovedDbFeedback(
        proposal=_proposal(),
        approved=True,
        approved_by="tester",
        approved_at=approved_at,
        approval_note="checked manually",
    )

    restored = ApprovedDbFeedback.model_validate_json(feedback.model_dump_json())

    assert restored == feedback
    assert restored.proposal.target.target_scope == "base"
    assert restored.approved_at == approved_at


def test_local_feedback_application_record_and_result_roundtrip():
    approved_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    record = LocalFeedbackApplicationRecord(
        application_id=1,
        proposal_hash="abc123",
        proposal_kind="translation_correction",
        target_kind="translation",
        target_scope="base",
        target_tag_id=10,
        format_name=None,
        field="translation.ja",
        approved_by="tester",
        approved_at=approved_at,
        status="applied",
        dry_run=False,
        proposal_json="{}",
        before_json=None,
        after_json='{"changes":[]}',
    )
    result = LocalFeedbackApplyResult(
        ok=True,
        status="applied",
        dry_run=False,
        proposal_hash="abc123",
        proposal_kind="translation_correction",
        message="feedback applied",
        changes=[],
        application=record,
    )

    restored = LocalFeedbackApplyResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert restored.application is not None
    assert restored.application.target_scope == "base"


def test_local_feedback_application_table_is_user_overlay_schema_only():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())

    assert "LOCAL_FEEDBACK_APPLICATIONS" in table_names
