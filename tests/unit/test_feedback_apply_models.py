from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from genai_tag_db_tools.db.schema import LocalFeedbackApplication, UserOverlayBase
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


def _application_values(
    *,
    proposal_hash: str = "abc123",
    proposal_kind: str = "translation_correction",
    target_kind: str = "translation",
    target_scope: str | None = "base",
    status: str = "applied",
    dry_run: bool = False,
    approved_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "proposal_hash": proposal_hash,
        "proposal_kind": proposal_kind,
        "target_kind": target_kind,
        "target_scope": target_scope,
        "target_tag_id": 10,
        "format_name": None,
        "field": "translation.ja",
        "approved_by": "tester",
        "approved_at": approved_at or datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
        "status": status,
        "dry_run": dry_run,
        "proposal_json": "{}",
        "before_json": None,
        "after_json": '{"changes":[]}',
        "error_message": None,
    }


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


def test_approved_db_feedback_requires_approved_true():
    approved_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        ApprovedDbFeedback(
            proposal=_proposal(),
            approved=False,
            approved_by="tester",
            approved_at=approved_at,
        )


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


@pytest.mark.parametrize(
    ("status", "dry_run"),
    [
        ("applied", True),
        ("dry_run", False),
    ],
)
def test_local_feedback_application_record_rejects_contradictory_dry_run_status(status: str, dry_run: bool):
    with pytest.raises(ValidationError):
        LocalFeedbackApplicationRecord(
            application_id=1,
            **_application_values(status=status, dry_run=dry_run),
        )


@pytest.mark.parametrize(
    "application_update",
    [
        {"proposal_kind": "typo_kind"},
        {"target_kind": "typo_target"},
    ],
)
def test_local_feedback_application_record_rejects_unknown_kinds(application_update: dict[str, object]):
    with pytest.raises(ValidationError):
        LocalFeedbackApplicationRecord(
            application_id=1,
            **(_application_values() | application_update),
        )


@pytest.mark.parametrize(
    ("ok", "status"),
    [
        (True, "failed"),
        (False, "applied"),
        (False, "dry_run"),
        (False, "skipped"),
    ],
)
def test_local_feedback_apply_result_rejects_contradictory_ok_status(ok: bool, status: str):
    with pytest.raises(ValidationError):
        LocalFeedbackApplyResult(
            ok=ok,
            status=status,
            dry_run=status == "dry_run",
            proposal_hash="abc123",
            proposal_kind="translation_correction",
            message="feedback apply result",
            changes=[],
            application=None,
        )


@pytest.mark.parametrize(
    ("status", "dry_run"),
    [
        ("applied", True),
        ("dry_run", False),
    ],
)
def test_local_feedback_apply_result_rejects_contradictory_dry_run_status(status: str, dry_run: bool):
    with pytest.raises(ValidationError):
        LocalFeedbackApplyResult(
            ok=True,
            status=status,
            dry_run=dry_run,
            proposal_hash="abc123",
            proposal_kind="translation_correction",
            message="feedback apply result",
            changes=[],
            application=None,
        )


@pytest.mark.parametrize(
    "application_update",
    [
        {"proposal_hash": "other-hash"},
        {"proposal_kind": "tag_name_correction"},
        {"status": "skipped"},
        {"dry_run": True},
    ],
)
def test_local_feedback_apply_result_rejects_mismatched_application(application_update: dict[str, object]):
    record = LocalFeedbackApplicationRecord(
        application_id=1,
        **_application_values(),
    ).model_copy(update=application_update)

    with pytest.raises(ValidationError):
        LocalFeedbackApplyResult(
            ok=True,
            status="applied",
            dry_run=False,
            proposal_hash="abc123",
            proposal_kind="translation_correction",
            message="feedback applied",
            changes=[],
            application=record,
        )


def test_local_feedback_application_table_is_user_overlay_schema_only():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())

    assert "LOCAL_FEEDBACK_APPLICATIONS" in table_names


def test_local_feedback_application_prevents_duplicate_applied_hashes():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            LocalFeedbackApplication.__table__.insert(),
            _application_values(proposal_hash="dry-run-can-repeat", status="dry_run", dry_run=True),
        )
        conn.execute(
            LocalFeedbackApplication.__table__.insert(),
            _application_values(proposal_hash="dry-run-can-repeat", status="applied", dry_run=False),
        )
        conn.execute(
            LocalFeedbackApplication.__table__.insert(),
            _application_values(proposal_hash="duplicate-applied", status="applied", dry_run=False),
        )

        with pytest.raises(IntegrityError):
            conn.execute(
                LocalFeedbackApplication.__table__.insert(),
                _application_values(proposal_hash="duplicate-applied", status="applied", dry_run=False),
            )


def test_local_feedback_application_allows_apply_after_dry_run_skip():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            LocalFeedbackApplication.__table__.insert(),
            _application_values(proposal_hash="dry-run-skip", status="skipped", dry_run=True),
        )
        conn.execute(
            LocalFeedbackApplication.__table__.insert(),
            _application_values(proposal_hash="dry-run-skip", status="applied", dry_run=False),
        )


def test_local_feedback_application_rejects_unknown_status():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                LocalFeedbackApplication.__table__.insert(),
                _application_values(status="applyed"),
            )


@pytest.mark.parametrize(
    "values",
    [
        {"proposal_kind": "typo_kind"},
        {"target_kind": "typo_target"},
    ],
)
def test_local_feedback_application_rejects_unknown_kinds(values: dict[str, object]):
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                LocalFeedbackApplication.__table__.insert(),
                _application_values(**values),
            )


@pytest.mark.parametrize(
    ("status", "dry_run"),
    [
        ("applied", True),
        ("dry_run", False),
    ],
)
def test_local_feedback_application_rejects_contradictory_dry_run_status(status: str, dry_run: bool):
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                LocalFeedbackApplication.__table__.insert(),
                _application_values(status=status, dry_run=dry_run),
            )


def test_local_feedback_application_rejects_unknown_target_scope():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)

    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                LocalFeedbackApplication.__table__.insert(),
                _application_values(target_scope="usr"),
            )


def test_local_feedback_application_normalizes_approved_at_to_utc():
    engine = create_engine("sqlite:///:memory:")
    UserOverlayBase.metadata.create_all(engine)
    jst = timezone(timedelta(hours=9))
    approved_at = datetime(2026, 6, 28, 21, 0, tzinfo=jst)

    with engine.begin() as conn:
        conn.execute(
            LocalFeedbackApplication.__table__.insert(),
            _application_values(approved_at=approved_at),
        )
        restored = conn.execute(select(LocalFeedbackApplication.__table__.c.approved_at)).scalar_one()

    assert restored == datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
