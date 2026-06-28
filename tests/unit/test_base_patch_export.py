"""Tests for exporting base correction patches from approved feedback (#61)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from genai_tag_db_tools.models import ApprovedDbFeedback, DbFeedbackProposal, ProposalTarget
from genai_tag_db_tools.services.base_patch.export import (
    export_base_patch_file,
    export_base_patches,
)

APPROVED_AT = datetime(2026, 6, 27, tzinfo=UTC)


def _feedback(proposal: DbFeedbackProposal, *, approved: bool = True) -> ApprovedDbFeedback:
    return ApprovedDbFeedback(
        proposal=proposal,
        approved=approved,
        approved_by="maintainer",
        approved_at=APPROVED_AT,
    )


def _proposal(**kwargs) -> DbFeedbackProposal:
    defaults = {"confidence": 0.8, "source": "unit_test", "reason_codes": [], "evidence": []}
    defaults.update(kwargs)
    return DbFeedbackProposal(**defaults)


def _alias_proposal(scope: str = "base") -> DbFeedbackProposal:
    return _proposal(
        kind="alias_addition",
        target=ProposalTarget(
            kind="alias",
            target_scope=scope,
            target_tag_id=2,
            format_name="unknown",
            preferred_scope="base",
            preferred_tag_id=1,
        ),
        current={"alias": False, "preferred_tag": None},
        proposed={"alias": True, "preferred_tag": "black hair", "tag": "blakc hair"},
        reason_codes=["typo_alias_candidate"],
        evidence=[{"candidate": "black hair", "distance": 1}],
    )


def _translation_proposal() -> DbFeedbackProposal:
    return _proposal(
        kind="translation_correction",
        target=ProposalTarget(
            kind="translation",
            target_scope="base",
            target_tag_id=3,
            language="ja",
        ),
        current={"language": "ja", "translation": "蓝眼睛", "tag": "blue eyes"},
        proposed={"translation": "青い目", "language": "ja"},
        reason_codes=["wrong_language_translation"],
    )


def _status_proposal() -> DbFeedbackProposal:
    return _proposal(
        kind="status_correction",
        target=ProposalTarget(
            kind="tag_status",
            target_scope="base",
            target_tag_id=7,
            format_name="unknown",
            field="TAG_STATUS.deprecated",
        ),
        current={"deprecated": False, "tag": "pixiv id"},
        proposed={"deprecated": True},
        reason_codes=["training_unsuitable", "external_id_tag"],
    )


def _type_proposal() -> DbFeedbackProposal:
    return _proposal(
        kind="type_correction",
        target=ProposalTarget(
            kind="tag_type",
            target_scope="base",
            target_tag_id=5,
            format_name="danbooru",
        ),
        current={"type_name": "general", "tag": "example character"},
        proposed={"type_name": "character"},
    )


def test_export_alias_addition() -> None:
    result = export_base_patches([_feedback(_alias_proposal())])
    assert result.exported_count == 1
    patch = result.patches[0]
    assert patch.patch_type == "alias_addition"
    assert patch.scope == "base"
    assert patch.target == {"target_type": "alias", "tag": "blakc hair", "format_name": "unknown"}
    assert patch.proposed["preferred_tag"] == "black hair"
    assert patch.proposed["alias"] is True
    assert patch.approved is True
    assert patch.approved_by == "maintainer"
    assert patch.patch_id and patch.patch_id.startswith("sha256:")


def test_export_translation_and_status_and_type() -> None:
    feedbacks = [
        _feedback(_translation_proposal()),
        _feedback(_status_proposal()),
        _feedback(_type_proposal()),
    ]
    result = export_base_patches(feedbacks)
    assert result.exported_count == 3
    by_type = {p.patch_type: p for p in result.patches}
    assert by_type["translation_correction"].target["field"] == "translation.ja"
    assert by_type["translation_correction"].proposed["translation"] == "青い目"
    assert by_type["status_correction"].target["field"] == "TAG_STATUS.deprecated"
    assert by_type["status_correction"].proposed["deprecated"] is True
    assert by_type["type_correction"].proposed["type_name"] == "character"


def test_patch_id_is_stable_across_export_runs() -> None:
    a = export_base_patches([_feedback(_alias_proposal())]).patches[0]
    b = export_base_patches([_feedback(_alias_proposal())]).patches[0]
    assert a.patch_id == b.patch_id


def test_user_scope_proposal_is_skipped() -> None:
    result = export_base_patches([_feedback(_alias_proposal(scope="user"))])
    assert result.exported_count == 0
    assert result.rows[0].status == "skipped_user_scope"


def test_review_only_proposal_is_skipped() -> None:
    proposal = _proposal(
        kind="format_relation_review",
        target=ProposalTarget(kind="format_relation", target_scope="base"),
        proposed=None,
    )
    result = export_base_patches([_feedback(proposal)])
    assert result.rows[0].status == "skipped_review_only"


def test_usage_correction_is_unsupported_for_base_patch() -> None:
    proposal = _proposal(
        kind="usage_correction",
        target=ProposalTarget(kind="usage", target_scope="base", target_tag_id=1, format_name="danbooru"),
        proposed={"count": 5},
    )
    result = export_base_patches([_feedback(proposal)])
    assert result.rows[0].status == "skipped_unsupported_type"


def test_unapproved_feedback_filtered_from_file(tmp_path: Path) -> None:
    approved = _feedback(_alias_proposal()).model_dump(mode="json")
    unapproved = approved.copy()
    unapproved["approved"] = False
    input_file = tmp_path / "feedback.jsonl"
    input_file.write_text(json.dumps(approved) + "\n" + json.dumps(unapproved) + "\n", encoding="utf-8")
    output_file = tmp_path / "patches.jsonl"

    result = export_base_patch_file(input_file, output_file)
    assert result.exported_count == 1
    written = [json.loads(line) for line in output_file.read_text(encoding="utf-8").splitlines()]
    assert len(written) == 1
    assert written[0]["patch_type"] == "alias_addition"


def test_export_validate_mode_marks_validated_and_reports(tmp_path: Path) -> None:
    good = _feedback(_status_proposal()).model_dump(mode="json")
    input_file = tmp_path / "feedback.jsonl"
    input_file.write_text(json.dumps(good) + "\n", encoding="utf-8")
    output_file = tmp_path / "patches.jsonl"
    report = tmp_path / "export.tsv"

    result = export_base_patch_file(input_file, output_file, validate=True, report=report)
    assert result.exported_count == 1
    patch = result.patches[0]
    assert patch.validated is True
    assert patch.validated_at is not None

    report_lines = report.read_text(encoding="utf-8").splitlines()
    assert report_lines[0].split("\t")[0] == "patch_id"
    assert any("exported" in line for line in report_lines[1:])


def test_export_file_is_loadable_by_validator(tmp_path: Path) -> None:
    from genai_tag_db_tools.services.base_patch.validate import validate_base_patch_file

    out = tmp_path / "patches.jsonl"
    # write via file API
    input_file = tmp_path / "feedback.jsonl"
    input_file.write_text(
        "\n".join(
            json.dumps(_feedback(p).model_dump(mode="json"))
            for p in (_alias_proposal(), _translation_proposal())
        ),
        encoding="utf-8",
    )
    export_base_patch_file(input_file, out)
    validation = validate_base_patch_file(out)
    assert validation.ok
    assert len(validation.items) == 2


def test_reader_resolves_names_when_proposal_lacks_hints() -> None:
    proposal = _proposal(
        kind="translation_correction",
        target=ProposalTarget(kind="translation", target_scope="base", target_tag_id=3, language="ja"),
        current={"language": "ja", "translation": "x"},
        proposed={"translation": "青い目", "language": "ja"},
    )
    reader = SimpleNamespace(
        get_tag_by_id=lambda tid: SimpleNamespace(tag="blue eyes") if tid == 3 else None
    )
    result = export_base_patches([_feedback(proposal)], reader=reader)
    assert result.patches[0].target["tag"] == "blue eyes"
