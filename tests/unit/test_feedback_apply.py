from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.schema import (
    Base,
    LocalFeedbackApplication,
    TagFormat,
    TagTypeFormatMapping,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
    UserTagTranslationPatch,
    UserTagUsagePatch,
)
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository
from genai_tag_db_tools.models import ApprovedDbFeedback, DbFeedbackProposal, ProposalTarget
from genai_tag_db_tools.services.feedback_apply import (
    apply_approved_feedback,
    list_local_feedback_applications,
)


@pytest.fixture()
def user_engine(tmp_path: Path):
    db_path = tmp_path / "feedback_apply.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def user_session_factory(user_engine):
    return sessionmaker(bind=user_engine, autoflush=False, autocommit=False)


@pytest.fixture()
def user_repo(user_session_factory):
    return UserTagRepository(user_session_factory)


def _proposal(
    kind: str,
    *,
    target: ProposalTarget,
    proposed: dict | None = None,
    current: dict | None = None,
) -> DbFeedbackProposal:
    return DbFeedbackProposal(
        kind=kind,
        target=target,
        current=current,
        proposed=proposed,
        confidence=0.9,
        source="test",
        reason_codes=["test_reason"],
    )


def _approved(proposal: DbFeedbackProposal, *, approved: bool = True) -> ApprovedDbFeedback:
    return ApprovedDbFeedback(
        proposal=proposal,
        approved=approved,
        approved_by="tester",
        approved_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
    )


def test_unapproved_feedback_is_rejected(user_repo):
    proposal = _proposal(
        "translation_correction",
        target=ProposalTarget(kind="translation", target_scope="base", target_tag_id=10, language="ja"),
        proposed={"language": "ja", "translation": "青い目"},
    )

    with pytest.raises(ValueError, match="approved"):
        apply_approved_feedback(_approved(proposal, approved=False), user_repository=user_repo)


def test_dry_run_does_not_write_patch_but_records_audit(user_repo, user_session_factory):
    proposal = _proposal(
        "translation_correction",
        target=ProposalTarget(kind="translation", target_scope="base", target_tag_id=10, language="ja"),
        proposed={"language": "ja", "translation": "青い目"},
    )

    result = apply_approved_feedback(_approved(proposal), user_repository=user_repo, dry_run=True)

    assert result.status == "dry_run"
    with user_session_factory() as session:
        assert session.query(UserTagTranslationPatch).count() == 0
        audit = session.query(LocalFeedbackApplication).one()
    assert audit.status == "dry_run"
    assert audit.dry_run is True


def test_translation_correction_applies_to_base_scope_without_user_tag_shadow(
    user_repo,
    user_session_factory,
):
    proposal = _proposal(
        "translation_correction",
        target=ProposalTarget(kind="translation", target_scope="base", target_tag_id=10, language="ja"),
        proposed={"language": "ja", "translation": "青い目"},
    )

    result = apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    assert result.status == "applied"
    with user_session_factory() as session:
        patch = session.query(UserTagTranslationPatch).one()
        assert patch.target_scope == "base"
        assert patch.target_tag_id == 10
        assert patch.language == "ja"
        assert patch.translation == "青い目"
        assert session.query(UserTag).count() == 0


def test_status_correction_writes_deprecated_overlay_patch(user_repo, user_session_factory):
    proposal = _proposal(
        "status_correction",
        target=ProposalTarget(
            kind="tag_status",
            target_scope="base",
            target_tag_id=20,
            format_name="unknown",
        ),
        proposed={"deprecated": True},
    )

    result = apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    assert result.status == "applied"
    with user_session_factory() as session:
        patch = session.query(UserTagStatusPatch).one()
        assert patch.target_scope == "base"
        assert patch.target_tag_id == 20
        assert patch.deprecated is True
        assert patch.alias is False
        assert patch.preferred_scope == "base"
        assert patch.preferred_tag_id == 20
        assert session.query(TagFormat).filter_by(format_name="unknown").one()


def test_type_correction_preserves_existing_status_fields(user_repo, user_session_factory):
    format_id = user_repo.get_or_create_format_id("danbooru")
    user_repo.write_patch(
        target_scope="base",
        target_tag_id=21,
        format_id=format_id,
        type_id=0,
        alias=False,
        preferred_scope="base",
        preferred_tag_id=21,
        deprecated=True,
    )
    proposal = _proposal(
        "type_correction",
        target=ProposalTarget(
            kind="tag_type",
            target_scope="base",
            target_tag_id=21,
            format_name="danbooru",
        ),
        proposed={"type_id": 4, "type_name": "character"},
    )

    apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    with user_session_factory() as session:
        patch = session.query(UserTagStatusPatch).one()
        assert patch.type_id == 4
        assert patch.deprecated is True
        assert patch.alias is False
        mapping = session.query(TagTypeFormatMapping).filter_by(format_id=format_id, type_id=4).one()
        assert mapping is not None


def test_alias_addition_creates_user_alias_without_copying_preferred_base_tag(
    user_repo,
    user_session_factory,
):
    proposal = _proposal(
        "alias_addition",
        target=ProposalTarget(
            kind="alias",
            target_scope="user",
            target_tag_id=None,
            format_name="danbooru",
            preferred_scope="base",
            preferred_tag_id=30,
        ),
        proposed={"alias_tag": "blakc hair", "type_name": "general"},
    )

    apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    with user_session_factory() as session:
        alias_tag = session.query(UserTag).filter_by(tag="blakc hair").one()
        patches = session.query(UserTagStatusPatch).all()
    assert len(patches) == 1
    assert patches[0].target_scope == "user"
    assert patches[0].target_tag_id == alias_tag.tag_id
    assert patches[0].alias is True
    assert patches[0].preferred_scope == "base"
    assert patches[0].preferred_tag_id == 30


def test_usage_correction_writes_usage_patch(user_repo, user_session_factory):
    proposal = _proposal(
        "usage_correction",
        target=ProposalTarget(
            kind="usage",
            target_scope="base",
            target_tag_id=40,
            format_name="danbooru",
        ),
        proposed={"count": 123},
    )

    apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    with user_session_factory() as session:
        patch = session.query(UserTagUsagePatch).one()
    assert patch.target_scope == "base"
    assert patch.target_tag_id == 40
    assert patch.count == 123


def test_tag_name_correction_creates_new_user_tag(user_repo, user_session_factory):
    proposal = _proposal(
        "tag_name_correction",
        target=ProposalTarget(kind="tag_name", target_scope="user", target_tag_id=None),
        current={"source_tag": "blue__eyes"},
        proposed={"tag": "blue eyes"},
    )

    apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    with user_session_factory() as session:
        tag = session.query(UserTag).one()
    assert tag.source_tag == "blue__eyes"
    assert tag.tag == "blue eyes"


def test_duplicate_apply_is_skipped(user_repo, user_session_factory):
    proposal = _proposal(
        "translation_correction",
        target=ProposalTarget(kind="translation", target_scope="base", target_tag_id=10, language="ja"),
        proposed={"language": "ja", "translation": "青い目"},
    )

    first = apply_approved_feedback(_approved(proposal), user_repository=user_repo)
    second = apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    assert first.status == "applied"
    assert second.status == "skipped"
    with user_session_factory() as session:
        assert session.query(UserTagTranslationPatch).count() == 1
        assert session.query(LocalFeedbackApplication).count() == 2


def test_list_local_feedback_applications_returns_audit_records(user_repo):
    proposal = _proposal(
        "translation_correction",
        target=ProposalTarget(kind="translation", target_scope="base", target_tag_id=10, language="ja"),
        proposed={"language": "ja", "translation": "青い目"},
    )
    apply_approved_feedback(_approved(proposal), user_repository=user_repo)

    records = list_local_feedback_applications(user_repository=user_repo)

    assert len(records) == 1
    assert records[0].proposal_kind == "translation_correction"
    assert records[0].target_scope == "base"
    assert records[0].target_tag_id == 10
    assert records[0].status == "applied"


def test_format_relation_review_is_not_applyable(user_repo):
    proposal = _proposal(
        "format_relation_review",
        target=ProposalTarget(kind="format_relation", target_scope="base", target_tag_id=10),
        proposed={"note": "review only"},
    )

    with pytest.raises(ValueError, match="unsupported"):
        apply_approved_feedback(_approved(proposal), user_repository=user_repo)
